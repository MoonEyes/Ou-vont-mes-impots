"""Éducation et recherche (pipeline/education_recherche.py) : règles de confidentialité, appariement, conservation,
coût par étudiant calculé, licences, liens. Sans réseau ; la reproduction complète demande l'entrepôt brut."""
from __future__ import annotations

import filecmp
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import education_recherche as er  # noqa: E402
import sirene  # noqa: E402

DATA = ROOT / "site" / "data" / "education_recherche"
FICHIERS = ["index.json", "anr_etablissements.json", "anr_projets.json", "collectivites_esr.json", "etudiants.json",
            "compte_education.json", "lycees/11.json", "lycees/24.json", "lycees/52.json"]


def charger(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


def identite(t, *_a, **_k):
    return t


# --- Unitaires : confidentialité à la lecture -------------------------------------------------------------------

def test_aucune_colonne_de_personne_n_est_lue():
    for cle, cols in er.COLONNES_LUES.items():
        for c in cols:
            assert not er.COLONNES_INTERDITES.search(c), (cle, c)
            # seule colonne « Adresse » admise : la région du partenaire (libellé de région, agrégé par région)
            if c != "Projet.Partenaire.Adresse.Region":
                assert not re.search(r"(?i)responsable|pr[eé]nom|orcid|ville|telephone|mail|fax|adresse", c), (cle, c)
    for interdit in ("Projet.Partenaire.Responsable_scientifique.Nom", "Projet.Partenaire.Responsable_scientifique.Prenom",
                     "Projet.Partenaire.Responsable_scientifique.ORCID", "Projet.Partenaire.Adresse.Ville",
                     "telephone", "mail", "adresse_1", "tiers", "dossier", "appellation_officielle"):
        assert er.COLONNES_INTERDITES.search(interdit), interdit


def test_sources_anr_en_zone_restreinte_et_declarees():
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    par_id = {s["id"]: s for s in cat["sources"]}
    for s in er.SOURCES.values():
        for i in s["catalogue"]:
            assert par_id[i]["domaine"] == er.DOMAINE and par_id[i]["licence"], i
    for i in ("edrech_anr_pia", "edrech_anr_2005_2009"):
        assert par_id[i]["personnes_physiques"] is True
        assert par_id[i]["licence"].startswith("ODbL")
    annuaire = par_id["edrech_annuaire_education"]["select"]
    assert not re.search(r"telephone|mail|fax|adresse|web", annuaire)
    assert "adresse" not in par_id["edrech_lycees_pdl"]["select"]
    assert "_restreint" in str(er.RESTREINT)


# --- Unitaires : appariement ANR / SIRENE -----------------------------------------------------------------------

def test_norme_et_cles():
    assert er.norme("Université d'Aix-Marseille ") == "UNIVERSITE D AIX MARSEILLE"
    assert er.cles_organisme("CNRS Alpes (Grenoble)") == [
        ("CNRS ALPES GRENOBLE", "denomination_identique"),
        ("CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE", "regle_organisme_national")]
    assert er.cles_organisme("Centre national de la recherche scientifique") == [
        ("CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE", "denomination_identique")]
    # une filiale est une autre personne morale : jamais rattachée à l'organisme par la règle
    assert [m for _, m in er.cles_organisme("INSERM TRANSFERT")] == ["denomination_identique"]
    assert [m for _, m in er.cles_organisme("CNRS Innovation")] == ["denomination_identique"]
    # un nom qui commence comme l'IRD sans être l'IRD
    assert [m for _, m in er.cles_organisme("Institut de recherche pour le développement personnel")] == [
        "denomination_identique"]
    assert er.cles_organisme(None) == []


def test_choisir_ne_retient_qu_une_personne_morale_unique():
    pm = ["180089013", "7389", "A", "CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE"]
    assert er.choisir([pm])[0]["siren"] == "180089013"
    assert er.choisir(None) == (None, "aucune_denomination_identique")
    assert er.choisir([pm, ["123456789", "5710", "A", "X"]]) == (None, "plusieurs_unites_legales")
    # une seule unité active parmi plusieurs
    assert er.choisir([pm, ["123456789", "5710", "C", "X"]])[0]["siren"] == "180089013"
    for cj in ("1000", "2110", "2385", "", None):
        assert er.choisir([["123456789", cj, "A", "DUPONT"]]) == (None, "non_personne_morale"), cj
    assert er.choisir([["12345", "5710", "A", "X"]]) == (None, "non_personne_morale")


def test_apparier_denomination_puis_regle():
    cand = {"CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE": [["180089013", "7389", "A", "CNRS-DENOM"]],
            "CNRS INNOVATION": [["111111111", "5710", "A", "CNRS INNOVATION"]],
            "UNIVERSITE X": [["222222222", "7383", "A", "UNIVERSITE X"], ["333333333", "9220", "A", "UNIVERSITE X"]]}
    r = er.apparier({"CNRS Alpes", "CNRS Innovation", "Université X", "Laboratoire Y", "INSERM Paris"}, cand)
    assert r["CNRS Alpes"] == {"siren": "180089013", "categorie_juridique": "7389", "denomination": "CNRS-DENOM",
                               "methode": "regle_organisme_national"}
    assert r["CNRS Innovation"]["siren"] == "111111111" and r["CNRS Innovation"]["methode"] == "denomination_identique"
    assert r["Université X"] == {"motif": "plusieurs_unites_legales"}
    assert r["Laboratoire Y"] == {"motif": "aucune_denomination_identique"}
    assert r["INSERM Paris"] == {"motif": "aucune_denomination_identique"}   # cible absente du stock : agrégé


def _brut_anr():
    part = lambda code, coord, nom, cat, region="Bretagne": {  # noqa: E731
        "Projet.Code_Decision": code, "Action.Edition": "2022", "Projet.Partenaire.Est_coordinateur": coord,
        "Projet.Partenaire.Nom_organisme": nom, "Projet.Partenaire.Categorie_organisme": cat,
        "Projet.Partenaire.Adresse.Region": region}
    anc = lambda code, coord, nom, aide: {  # noqa: E731
        "Projet.Code_Decision": code, "Projet.Partenaire.Est_coordinateur": coord,
        "Projet.Partenaire.Nom_organisme": nom, "Projet.Partenaire.Categorie_organisme": "Université",
        "Projet.Partenaire.Aide_allouee.ANR": aide}
    return {
        "pia_partenaires": [part("P1", "True", "Université X", "Universités"), part("P1", "False", "Labo Y", "EPST"),
                            part("P2", "True", "Labo Y", "EPST", None)],
        "pia_projets": [{"Projet.Code_Decision": "P1", "Action.Edition": "2022", "Action.Titre.Francais": "LABX",
                         "Projet.Aide_allouee": "1000.5"},
                        {"Projet.Code_Decision": "P2", "Action.Edition": "2023", "Action.Titre.Francais": "EQPX",
                         "Projet.Aide_allouee": "200"}],
        "a_partenaires": [anc("A1", "True", "Université X", "300"), anc("A1", "False", "Labo Y", ""),
                          anc("A1", "False", "Labo Y", "50")],
        "a_projets": [{"Projet.Code_Decision": "A1", "AAP.Edition": "2007", "Programme.Acronyme": "BLANC",
                       "Projet.Montant.AF.Aide_allouee.ANR": "360"}],
    }


def test_anr_conservation_et_agregation_des_non_apparies():
    ratt = {"Université X": {"siren": "222222222", "categorie_juridique": "7383", "denomination": "UNIVERSITE X",
                             "methode": "denomination_identique"},
            "Labo Y": {"motif": "aucune_denomination_identique"}}
    f2030 = {"par_operateur": {"ANR": {"total_eur": 1000.0, "projets": 3, "top": [{"siren": "222222222"}]}}}
    etab, proj, resume = er.construire_anr(_brut_anr(), ratt, f2030)
    pia = etab["pia_france2030"]
    assert pia["etablissements"] == [["222222222", "UNIVERSITE X", "7383", "denomination_identique", ["Universités"],
                                      1, 1, 1000.5, 0, 2022, 2022, True]]
    assert pia["non_nommes"]["par_categorie"] == [{"categorie": "EPST", "organismes": 1, "participations": 2,
                                                   "projets_coordonnes": 1, "aide_projets_coordonnes_eur": 200.0,
                                                   "lignes_sans_montant": 0}]
    assert pia["total"]["aide_projets_coordonnes_eur"] == pia["total_projets"]["aide_eur"] == 1200.5
    anc = etab["anr_2005_2009"]
    assert anc["nommes"]["aide_allouee_eur"] == 300 and anc["non_nommes"]["aide_allouee_eur"] == 50
    assert anc["total"]["lignes_sans_montant"] == 1          # aide absente : comptée, jamais 0
    assert "Labo Y" not in json.dumps(etab, ensure_ascii=False)   # non apparié : jamais nommé
    assert proj["pia_france2030"]["par_annee"] == [
        {"annee": 2022, "projets": 1, "aide_eur": 1000.5, "participations": 2},
        {"annee": 2023, "projets": 1, "aide_eur": 200.0, "participations": 1}]
    assert [r["region"] for r in proj["pia_france2030"]["par_region"]] == ["Bretagne", None]
    e = proj["ecarts"][0]
    assert (e["montant"], e["autre_montant"], e["ecart"]) == (360.0, 350.0, 10.0)
    assert proj["ecarts"][1]["autre_montant"] == 1000.0 and resume["lien"]["id"] == "par_operateur.ANR"


# --- Unitaires : lycées --------------------------------------------------------------------------------------------

def test_lycees_personne_morale_nommee_sinon_agregee():
    annuaire = {"0440001A": {"nom": "Lycée A", "type": "Lycée", "secteur": "Public", "code_commune": "44109",
                             "commune": "Nantes", "departement_nom": "Loire-Atlantique", "academie": "Nantes",
                             "siren": "194400001"},
                "0440002B": {"nom": "Lycée B", "type": "Lycée", "secteur": "Privé", "code_commune": "44109",
                             "commune": "Nantes", "departement_nom": "Loire-Atlantique", "academie": "Nantes",
                             "siren": "500000001"}}
    unites = {"194400001": ("7331", "LYCEE A"), "500000001": ("1000", None)}
    li = lambda an, uai, m, d="Axe 1": {"annee": an, "uai": uai, "siren": None, "dispositif": d, "montant": m,  # noqa: E731
                                        "type_tiers": None, "code_commune": None}
    lignes = [li(2018, "0440001A", 100.0), li(2019, "0440001A", 0.0), li(2019, "0440001A", None),
              li(2018, "0440002B", 40.0), li(2019, "0449999Z", 5.0), li(None, "0440001A", 7.0)]
    d = er.construire_lycees("52", lignes, annuaire, unites, publiable=identite)
    assert d["etablissements"] == [["0440001A", "194400001", "Lycée A", "7331", "Public", "Lycée", "44109", "44",
                                    "Nantes", 100.0, [100.0, 0.0]]]
    assert d["non_nommes"]["motifs"] == {
        "personne_physique_ou_groupement": {"nombre": 1, "montant_eur": 40.0},
        "uai_absent_de_l_annuaire_ou_sans_siret": {"nombre": 1, "montant_eur": 5.0}}
    assert "Lycée B" not in json.dumps(d, ensure_ascii=False)
    assert d["total_eur"] == 145.0 == d["nommes"]["montant_eur"] + d["non_nommes"]["montant_eur"]
    a2019 = d["par_annee"][1]
    assert (a2019["lignes_montant_zero"], a2019["lignes_montant_absent"], a2019["total_eur"]) == (1, 1, 5.0)
    assert d["lignes_sans_annee"] == {"lignes": 1, "montant_eur": 7.0}
    assert sum(c["total_eur"] for c in d["par_commune"]) == sum(c["total_eur"] for c in d["par_departement"]) == 145.0
    assert [c["departement"] for c in d["par_departement"]] == ["44"]      # 0449999Z : département lu dans l'UAI


def test_uai_et_departement():
    assert er.uai_propre(" 0440001a ") == "0440001A" and er.uai_propre("940877T") is None
    assert er.dep_de_uai("0180005H") == "18" and er.dep_de_uai("9740001A") == "974"
    assert er.dep_de_uai("6200001A") == "2A" and er.dep_de_uai("x") is None
    assert er.dep_de_commune("97411") == "974" and er.dep_de_commune("2A004") == "2A" and er.dep_de_commune("") is None


# --- Unitaires : collectivités et coût par étudiant --------------------------------------------------------------

def _budget(an, reg, cat, m, qualite="définitif", type_co="CR"):
    return {"millesime": str(an), "qualite": qualite, "groupe_reg": "METRO", "code_reg": reg, "lib_reg": f"Région {reg}",
            "type_co": type_co, "lib_type_co": type_co, "cat_depenses": cat, "code_var": "2500" if "Ens" in cat else "1500",
            "lib_var": "x", "montant": m}


def _effectif(an, ident, reg, n, attention="Sans double compte"):
    return {"annee_universitaire": f"{an - 1}-{str(an)[2:]}", "annee": str(an), "attention": attention,
            "etablissement_type": "Université", "etablissement_typologie": None, "etablissement_id_paysage": ident,
            "etablissement_lib": f"Université {ident}", "etablissement_id_uai": "0440984F", "effectif": n + 10,
            "effectif_sans_cpge": n, "etablissement_id_region": reg, "etablissement_region": "R",
            "etablissement_id_departement": "D044", "etablissement_departement": "Loire-Atlantique",
            "etablissement_academie": "Nantes", "etablissement_code_commune": "44109", "etablissement_commune": "Nantes"}


def test_cout_par_etudiant_calcule_avec_sa_formule():
    esve, rt = "Enseignement supérieur et vie étudiante", "Recherche et transfert de technologie"
    coll = er.construire_collectivites([
        _budget(2023, "52", esve, 1000.0), _budget(2023, "52", esve, 500.0, type_co="CD"), _budget(2023, "52", rt, 70.0),
        _budget(2024, "52", rt, 80.0, "semi-définitif"), _budget(2023, "974", esve, 90.0), _budget(2023, "11", esve, None)])
    assert [g["code"] for g in coll["regions"]] == ["52", "974"]     # région 11 : aucun montant publié, aucune série
    r52 = coll["regions"][0]
    assert (r52["esve_eur"], r52["rt_eur"]) == ([1500.0, None], [70.0, 80.0])     # absence : null, jamais 0
    assert coll["lignes_sans_montant"] == 1 and coll["qualite"] == {"2023": "définitif", "2024": "semi-définitif"}
    etu = er.construire_etudiants([
        _effectif(2023, "a", "R52", 100), _effectif(2023, "b", "R52", 50),
        _effectif(2023, "c", "R52", 999, "* Attention : doubles comptes, établissement-composante"),
        _effectif(2024, "a", "R52", 120), _effectif(2023, "d", "R04", 30)], coll, {})
    c = etu["cout_par_etudiant"]
    assert c["statut"] == "calculé" and "budget_esve_eur / etudiants" in c["formule"]
    v = {r["code"]: r["valeurs"] for r in c["regions"]}
    # Règle « chiffre calculé par le site » : années civile et universitaire différentes, coût non publié (motif).
    assert v["52"][0] == {"annee": 2023, "qualite_budget": "définitif", "budget_esve_eur": 1500.0, "etudiants": 150,
                          "cout_par_etudiant_eur": None, "statut": None, "mention": er.MOTIF_REGLE_CALCULE}
    assert v["52"][1]["cout_par_etudiant_eur"] is None and v["52"][1]["statut"] is None   # budget absent en 2024
    assert "non publiée" in v["52"][1]["mention"] and v["52"][0]["mention"] == er.MOTIF_REGLE_CALCULE
    # national 2024 : la catégorie « enseignement supérieur » n'est pas publiée : null avec mention, jamais 0
    n24 = coll["national"][1]
    assert (n24["esve_eur"], n24["total_eur"], n24["rt_eur"], n24["categories_publiees"]) == (None, None, 80.0, ["rt"])
    assert "pas 0" in n24["mention"] and coll["national"][0]["mention"] is None
    nat24 = c["national"][1]
    assert (nat24["budget_esve_eur"], nat24["cout_par_etudiant_eur"], nat24["statut"]) == (None, None, None)
    assert nat24["etudiants"] == 120 and nat24["mention"]
    assert v["974"][0]["etudiants"] == 30 and v["974"][0]["cout_par_etudiant_eur"] is None   # R04 rapproché de 974
    assert next(g for g in etu["par_region"] if g["region"] == "52")["etudiants"] == [150, 120]              # composante en double compte exclue
    ligne = next(e for e in etu["etablissements"] if e[0] == "c")
    assert ligne[12] is True and ligne[2] is None


def test_aucune_absence_comptee_zero_unitaire():
    assert er.somme([]) is None and er.somme([None, None]) is None and er.somme([None, 0.0]) == 0.0
    assert er.ajoute(None, None) is None and er.ajoute(None, 2) == 2 and er.ajoute(1, None) == 1
    # ANR 2005-2009 : un organisme dont aucune aide n'est publiée a un montant null, pas 0
    brut = _brut_anr()
    brut["a_partenaires"].append({"Projet.Code_Decision": "A1", "Projet.Partenaire.Est_coordinateur": "False",
                                  "Projet.Partenaire.Nom_organisme": "Labo Z",
                                  "Projet.Partenaire.Categorie_organisme": "EPIC", "Projet.Partenaire.Aide_allouee.ANR": ""})
    brut["pia_partenaires"].append({"Projet.Code_Decision": "P1", "Action.Edition": "2022",
                                    "Projet.Partenaire.Est_coordinateur": "False", "Projet.Partenaire.Nom_organisme": "Labo Z",
                                    "Projet.Partenaire.Categorie_organisme": "EPIC",
                                    "Projet.Partenaire.Adresse.Region": "Corse"})
    ratt = {"Université X": {"siren": "222222222", "categorie_juridique": "7383", "denomination": "UNIVERSITE X",
                             "methode": "denomination_identique"}}
    etab, proj, _ = er.construire_anr(brut, ratt, None)
    epic = next(x for x in etab["anr_2005_2009"]["non_nommes"]["par_categorie"] if x["categorie"] == "EPIC")
    assert epic["aide_allouee_eur"] is None and epic["lignes_sans_montant"] == 1
    epic_pia = next(x for x in etab["pia_france2030"]["non_nommes"]["par_categorie"] if x["categorie"] == "EPIC")
    assert epic_pia["aide_projets_coordonnes_eur"] is None and epic_pia["projets_coordonnes"] == 0
    corse = next(r for r in proj["pia_france2030"]["par_region"] if r["region"] == "Corse")
    assert corse["aide_projets_coordonnes_eur"] is None
    # séries : un groupe sans aucune valeur publiée reste null
    assert er.series([{"k": 1, "m": None}, {"k": 2, "m": 0.0}], "k", ["m"]) == [{"k": 1, "m": None}, {"k": 2, "m": 0.0}]
    # lycées : une année dont toutes les lignes sont sans montant a un total null, pas 0
    li = lambda an, m: {"annee": an, "uai": None, "siren": None, "dispositif": "A", "montant": m,  # noqa: E731
                        "type_tiers": "Commune", "code_commune": None}
    d = er.construire_lycees("52", [li(2018, 10.0), li(2019, None)], {}, {}, publiable=identite)
    a2019 = d["par_annee"][1]
    assert (a2019["total_eur"], a2019["nommes_eur"], a2019["non_nommes_eur"], a2019["lignes_montant_absent"]) == (
        None, None, None, 1)
    assert d["lignes_sans_annee"] == {"lignes": 0, "montant_eur": None}


def _tableur_compte(menages_2024=7.7):
    f1 = [("Figure 1 – Dépense intérieure d’éducation",),
          ("Dépenses d'éducation et structure du financement", 2010, 2023, "2024p"),
          ("DIE en valeur (en milliards d’euros courants) ", 139.3, 190.3, 197.1),
          ("DIE en milliards d'euros constants¹ (aux prix 2024)", 173.3, 194.3, 197.1),
          ("Dépense moyenne en euros courants", 8070, 10510, 10920),
          ("Dépense moyenne en euros constants (aux prix 2024)", 10040, 10730, 10920),
          ("État, dont : ", 57.9, 55, 55.2), ("MEN-MESRE²", 52.9, 51.2, 51.6),
          ("Collectivités territoriales", 23.9, 23, 23),
          ("Autres administrations publiques et caisses d’allocations familiales", 2.3, 3.8, 3.8),
          ("Entreprises", 8.3, 10.4, 10.3), ("Ménages", 7.6, 7.9, menages_2024),
          ("Lecture : En 2024, la dépense moyenne par élève ou étudiant s’élève à 10 920 euros.",),
          ("Champ : France.",), ("Source\xa0: MEN-MESRE-Depp, Compte de l’éducation.",)]
    f2 = [("Figure 2",), ("Année", "Part de la DIE dans le PIB (en %)", "DIE (en milliards d’euros 2024)"),
          (2023, 6.7, 194.3), (2024, 6.8, None)]
    f3 = [("Figure 3 – Dépense moyenne par élève ou étudiant selon le niveau de formation en 2024",),
          (None, None, "en euros"), ("Niveau de formation", None, "Dépense moyenne par élève"),
          ("Premier degré ", "Préélémentaire", 8990), (None, "Ensemble", 9080),
          ("Second degré¹", "Collège", 10450), (None, "Ensemble", 11660),
          ("Supérieur¹", "Université", 12460), (None, "Ensemble", 13300)]
    f4 = [("Figure 4",), (None, None, "en euros constants, prix 2024"),
          ("Année", "Dépense moyenne par élève", "Dépense moyenne pour un élève du 1er degré",
           "Dépense moyenne pour un élève du 2nd degré", "Dépense moyenne pour un élève du supérieur"),
          (2023, 10730, 8660, 11550, 13480), ("2024p", 10920, 9080, 11660, 13300)]
    return {"figure1": f1, "figure2": f2, "figure3": f3, "figure4": f4}


def test_compte_education_familles_entreprises_et_depense_par_eleve():
    c = er.construire_compte_education(_tableur_compte())
    fi = c["financement_initial"]
    assert fi["annees"] == [2010, 2023, 2024] and fi["provisoire"] == [False, False, True]
    assert fi["familles_et_entreprises"] == dict(fi["familles_et_entreprises"], annee=2024, provisoire=True,
                                                 menages_pct=7.7, entreprises_pct=10.3)
    assert [x["somme_pct"] for x in fi["controle_somme"]] == [100.0, 100.1, 100.0]
    assert next(f for f in fi["financeurs"] if f["id"] == "etat_ministeres_education")["parent"] == "etat"
    n = c["depense_moyenne_par_niveau"]
    assert n["annee"] == 2024 and n["provisoire"] is True
    assert {(x["degre"], x["niveau"]): x["depense_moyenne_eur"] for x in n["niveaux"]}[("second_degre", "Collège")] == 10450
    assert c["die_serie"]["die_md_eur_constants"] == [194.3, None]          # cellule vide : null, jamais 0
    assert c["die_serie"]["prix_constants"] == "2024" and c["champ"] == "France"
    ev = c["depense_moyenne_evolution"]
    assert [s["id"] for s in ev["series"]] == ["ensemble", "premier_degre", "second_degre", "superieur"]
    assert ev["provisoire"] == [False, True]
    # une part absente du tableur reste null, et la somme de contrôle aussi
    c2 = er.construire_compte_education(_tableur_compte(menages_2024=None))
    assert c2["financement_initial"]["familles_et_entreprises"]["menages_pct"] is None
    assert c2["financement_initial"]["controle_somme"][-1]["somme_pct"] is None


# --- Données publiées ------------------------------------------------------------------------------------------------

pytestmark_donnees = pytest.mark.skipif(not (DATA / "index.json").exists(), reason="site/data/education_recherche absent")


@pytestmark_donnees
def test_fichiers_conformes_aux_schemas_et_sous_5_mo():
    import valider_contrat as vc
    js = vc.charger_jsonschema()
    motifs = {m: s for s, m, _ in vc.FICHIERS if m.startswith("education_recherche/")}
    assert len(motifs) == 7
    vus = 0
    for motif, schema in motifs.items():
        for p in sorted((ROOT / "site" / "data").glob(motif)):
            doc = json.loads(p.read_text(encoding="utf-8"))
            assert not vc.erreurs(vc.validateur(js, schema), doc), p.name
            assert not vc.liens_fichiers(p, doc), p.name
            assert p.stat().st_size < 5_000_000 and doc["millesime"] and "http" in doc["source"], p.name
            vus += 1
    assert vus == len(FICHIERS)
    assert sorted(str(p.relative_to(DATA)) for p in DATA.rglob("*.json")) == sorted(FICHIERS)


@pytestmark_donnees
def test_seules_des_personnes_morales_sont_nommees():
    anr = charger("anr_etablissements.json")
    for bloc in ("pia_france2030", "anr_2005_2009"):
        i = anr[bloc]["colonnes"].index("categorie_juridique")
        assert anr[bloc]["etablissements"]
        for e in anr[bloc]["etablissements"]:
            assert sirene.siren_valide(e[0]) and sirene.personne_morale(e[i]), e[:3]
    for code in ("11", "24", "52"):
        d = charger(f"lycees/{code}.json")
        for e in d["etablissements"]:
            assert sirene.siren_valide(e[1]) and sirene.personne_morale(e[3]) and e[2], e[:4]
    for e in charger("etudiants.json")["etablissements"]:
        assert (e[2] is None) == (e[3] is None) and (e[2] is None or sirene.personne_morale(e[3])), e[:5]


@pytestmark_donnees
def test_aucune_trace_des_colonnes_supprimees():
    interdits = re.compile(r"(?i)responsable_scientifique|\"orcid|\"pr[eé]nom|\"telephone|\"mail|\"courriel|\"adresse"
                           r"|\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")             # identifiant ORCID
    for nom in FICHIERS:
        texte = (DATA / nom).read_text(encoding="utf-8")
        assert not interdits.search(texte), nom
        assert not re.search(r"\b0[1-9](?:[ .]?\d{2}){4}\b", texte), nom          # numéro de téléphone
        assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", texte), nom            # courriel


@pytestmark_donnees
def test_conservation_anr():
    anr = charger("anr_etablissements.json")
    for bloc, champ in (("pia_france2030", "aide_projets_coordonnes_eur"), ("anr_2005_2009", "aide_allouee_eur")):
        b = anr[bloc]
        for c in ("participations", "projets_coordonnes"):
            assert b["nommes"][c] + b["non_nommes"][c] == b["total"][c], (bloc, c)
        assert abs(b["nommes"][champ] + b["non_nommes"][champ] - b["total"][champ]) < 1, bloc
        assert abs(sum(x[champ] or 0 for x in b["non_nommes"]["par_categorie"]) - b["non_nommes"][champ]) < 1
        assert sum(b["non_nommes"]["motifs"].values()) == b["non_nommes"]["participations"]
        i = b["colonnes"].index(champ)
        cle = lambda e: (e[i] is None, -(e[i] or 0), -e[5], e[1], e[0])  # noqa: E731
        assert [cle(e) for e in b["etablissements"]] == sorted(cle(e) for e in b["etablissements"])
    pia = anr["pia_france2030"]
    # PIA : toute l'aide par projet est rattachée à un coordinateur, nommé ou agrégé
    assert abs(pia["total"]["aide_projets_coordonnes_eur"] + (pia["total_projets"]["aide_projets_sans_coordinateur_eur"] or 0)
               - pia["total_projets"]["aide_eur"]) < 1
    proj = charger("anr_projets.json")
    assert abs(sum(a["aide_eur"] for a in proj["pia_france2030"]["par_annee"]) - pia["total_projets"]["aide_eur"]) < 1
    assert abs(sum(a["aide_eur"] or 0 for a in proj["pia_france2030"]["par_action"]) - pia["total_projets"]["aide_eur"]) < 1
    assert sum(r["participations"] for r in proj["pia_france2030"]["par_region"]) == pia["total"]["participations"]
    anc = proj["anr_2005_2009"]
    assert [a["annee"] for a in anc["par_annee"]] == [2005, 2006, 2007, 2008, 2009]
    assert abs(sum(g["aide_projets_eur"] for g in anc["par_programme"]) + anc["par_programme_autres"]["aide_projets_eur"]
               - anc["total"]["aide_projets_eur"]) < 1
    for e in proj["ecarts"]:
        assert abs(e["montant"] - e["autre_montant"] - e["ecart"]) < 0.02 and e["lecture"]


@pytestmark_donnees
@pytest.mark.parametrize("code", ["11", "24", "52"])
def test_conservation_lycees(code):
    d = charger(f"lycees/{code}.json")
    n = len(d["annees"])
    total = d["total_eur"]
    assert abs(d["nommes"]["montant_eur"] + d["non_nommes"]["montant_eur"] - total) < 1
    assert abs(sum(e[9] for e in d["etablissements"]) - d["nommes"]["montant_eur"]) < 1
    assert abs(sum(m["montant_eur"] for m in d["non_nommes"]["motifs"].values()) - d["non_nommes"]["montant_eur"]) < 1
    for cle in ("par_commune", "par_departement"):
        assert abs(sum(g["total_eur"] for g in d[cle]) - total) < 1, cle
        assert all(len(g["montants_eur"]) == n for g in d[cle])
    assert abs(sum(g["total_eur"] for g in d["par_dispositif"]) + d["par_dispositif_autres"]["total_eur"] - total) < 1
    for i, a in enumerate(d["par_annee"]):
        assert a["annee"] == d["annees"][i]
        assert abs(a["nommes_eur"] + a["non_nommes_eur"] - a["total_eur"]) < 1
        assert abs(sum(g["montants_eur"][i] or 0 for g in d["par_departement"]) - a["total_eur"]) < 1
    assert abs(sum(a["total_eur"] for a in d["par_annee"]) - total) < 1
    for e in d["etablissements"]:
        assert len(e[10]) == n and abs(sum(m or 0 for m in e[10]) - e[9]) < 0.02
        assert e[0] is None or er.UAI_RE.match(e[0])
    for c in d.get("controles", []):
        assert abs(c["ecart_eur"]) < 1


@pytestmark_donnees
def test_cout_par_etudiant_publie_recalcule():
    etu, coll = charger("etudiants.json"), charger("collectivites_esr.json")
    c = etu["cout_par_etudiant"]
    assert c["statut"] == "calculé" and c["formule"] == er.FORMULE_COUT and len(c["limites"]) >= 4
    budget = {g["code"]: g for g in coll["regions"]}
    calcules = 0
    for r in c["regions"]:
        for v in r["valeurs"]:
            attendu = budget[r["code"]]["esve_eur"][coll["annees"].index(v["annee"])] if r["code"] in budget else None
            assert v["budget_esve_eur"] == attendu, (r["code"], v["annee"])
            # Règle « chiffre calculé par le site » : jamais publié, motif écrit.
            assert v["cout_par_etudiant_eur"] is None and v["statut"] is None and v["mention"]
            if v["budget_esve_eur"] is not None and v["etudiants"]:
                assert v["mention"] == er.MOTIF_REGLE_CALCULE
                calcules += 1
    assert calcules > 100
    par_region = {er.REGIONS_OUTRE_MER.get(g["region"], g["region"]): g for g in etu["par_region"]}
    idf = next(r for r in c["regions"] if r["code"] == "11")
    for v in idf["valeurs"]:
        assert v["etudiants"] == par_region["11"]["etudiants"][etu["annees"].index(v["annee"])]
    assert charger("index.json")["cout_par_etudiant"]["national"] == c["national"]
    for nat in coll["national"]:
        if nat["total_eur"] is None:
            assert nat["categories_publiees"] != ["rt", "esve"] and nat["mention"]
            continue
        assert abs(nat["rt_eur"] + nat["esve_eur"] - nat["total_eur"]) < 1
        assert abs(sum(nat["par_type"].values()) - nat["total_eur"]) < 1


@pytestmark_donnees
def test_aucun_zero_a_la_place_d_une_absence():
    coll, etu, idx = charger("collectivites_esr.json"), charger("etudiants.json"), charger("index.json")
    sans_esve = [n["annee"] for n in coll["national"] if "esve" not in n["categories_publiees"]]
    assert sans_esve == list(range(2006, 2015))          # la source ne publie pas cette catégorie avant 2015
    for n in coll["national"]:
        if "esve" not in n["categories_publiees"]:
            assert n["esve_eur"] is None and n["total_eur"] is None and n["mention"], n["annee"]
        for k in ("rt_eur", "esve_eur", "total_eur"):
            assert n[k] != 0, (n["annee"], k)
    budgets = {n["annee"]: n["esve_eur"] for n in coll["national"]}
    for liste in (etu["cout_par_etudiant"]["national"], idx["cout_par_etudiant"]["national"]):
        for v in liste:
            assert v["budget_esve_eur"] == budgets[v["annee"]]
            assert v["cout_par_etudiant_eur"] != 0 and v["budget_esve_eur"] != 0, v["annee"]
            if v["budget_esve_eur"] is None:
                assert v["cout_par_etudiant_eur"] is None and v["statut"] is None and v["mention"], v["annee"]
    for r in etu["cout_par_etudiant"]["regions"]:
        for v in r["valeurs"]:
            assert (v["cout_par_etudiant_eur"] is None) == bool(v["mention"]), (r["code"], v["annee"])
    anr = charger("anr_etablissements.json")
    b = anr["anr_2005_2009"]
    i, j = b["colonnes"].index("aide_allouee_eur"), b["colonnes"].index("lignes_sans_montant")
    for e in b["etablissements"]:
        if e[j] == e[5]:                                   # aucune aide publiée pour l'organisme
            assert e[i] is None, e[:2]
    p = anr["pia_france2030"]
    i = p["colonnes"].index("aide_projets_coordonnes_eur")
    for e in p["etablissements"]:
        assert (e[6] == 0) == (e[i] is None), e[:2]       # aucun projet coordonné : aide non publiée, null
    for code in ("11", "24", "52"):
        for a in charger(f"lycees/{code}.json")["par_annee"]:
            if a["lignes"] and a["lignes_montant_absent"] == a["lignes"]:
                assert a["total_eur"] is None, (code, a["annee"])


@pytestmark_donnees
def test_compte_education_publie():
    c = charger("compte_education.json")
    fi = c["financement_initial"]
    fe = fi["familles_et_entreprises"]
    assert fe["annee"] == fi["annees"][-1] and fe["menages_pct"] and fe["entreprises_pct"]
    assert all(x["somme_pct"] is None or abs(x["somme_pct"] - 100) <= 0.3 for x in fi["controle_somme"])
    degres = {x["degre"] for x in c["depense_moyenne_par_niveau"]["niveaux"] if x["ensemble_du_degre"]}
    assert degres == {"premier_degre", "second_degre", "superieur"}
    assert "Depp" in fi["source_citee"] and "insee.fr" in c["source"] and c["licence"] == "Licence Ouverte 2.0"
    idx = charger("index.json")
    assert idx["fichiers"]["compte_education"] == "education_recherche/compte_education.json"
    assert idx["totaux"]["compte_education"]["menages_pct"] == fe["menages_pct"]
    assert "compte_education" in {s["id"] for s in idx["sources"]}


@pytestmark_donnees
def test_licences_odbl_declarees_et_lien_france2030_sans_copie():
    idx = charger("index.json")
    odbl = {x["source"] for x in idx["licences"]["odbl"]}
    assert odbl == {"anr_pia", "anr_2005_2009", "lycees_cvl", "lycees_pdl"}
    assert all(x["url_licence"] == er.URL_ODBL for x in idx["licences"]["odbl"])
    assert charger("anr_etablissements.json")["licence"] == "ODbL 1.0" == charger("anr_projets.json")["licence"]
    assert charger("lycees/24.json")["licence"] == "ODbL 1.0" == charger("lycees/52.json")["licence"]
    assert charger("lycees/11.json")["licence"] == "Licence Ouverte 2.0"
    assert {s["id"] for s in idx["sources"]} == set(er.SOURCES)
    assert all(t["verdict"] and "licence" in t for t in idx["recherche_publique"]["trouvailles"])
    f2030 = json.loads((ROOT / "site" / "data" / "beneficiaires" / "france2030.json").read_text(encoding="utf-8"))
    lien = idx["liens"][0]
    assert lien["fichier"] == "beneficiaires/france2030.json" and lien["id"] == "par_operateur.ANR"
    assert lien["total_eur"] == f2030["par_operateur"]["ANR"]["total_eur"]
    # relié, pas recopié : aucun montant par bénéficiaire du fichier France 2030 n'est repris dans l'axe
    pia = charger("anr_etablissements.json")["pia_france2030"]
    sirens = {b["siren"] for b in f2030["par_operateur"]["ANR"]["top"]}
    assert {e[0] for e in pia["etablissements"] if e[11]} <= sirens
    assert "top" not in pia and "par_operateur" not in json.dumps(idx["totaux"])


@pytestmark_donnees
def test_reproduction_identique_si_entrepot_present(tmp_path):
    sources = [er.BRUT / "edrech_lycees_idf.parquet", er.STOCK_SIRENE, er.RESTREINT / "edrech_anr_pia",
               er.FICHIER_COMPTE]
    if not all(p.exists() for p in sources):
        pytest.skip("entrepôt brut absent (data/lake/education_recherche, stock SIRENE)")
    er.produire(tmp_path)
    for nom in FICHIERS:
        assert filecmp.cmp(tmp_path / nom, DATA / nom, shallow=False), nom
