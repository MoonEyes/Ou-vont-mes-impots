"""Fonction publique (pipeline/fonction_publique.py) : lecture des sources, confidentialité, cohérence des sorties.

Sans réseau ni entrepôt : fonctions de lecture testées sur des extraits construits à la main, sorties testées sur
site/data/fonction_publique (versionné).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import fonction_publique as fp  # noqa: E402

DATA = ROOT / "site" / "data"
FP = DATA / "fonction_publique"
FICHIERS = ["index", "effectifs_series", "emploi", "territoires", "ministeres", "cabinets", "conseils",
            "indemnites_elus"]


def charger(nom: str) -> dict:
    p = FP / f"{nom}.json"
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


def mot(t: str, x0: float, top: float = 100.0) -> dict:
    return {"text": t, "x0": x0, "x1": x0 + 4.5 * len(t), "top": top}


# --- Lecture : nombres et valeurs absentes ---------------------------------------------------------------------------

def test_nombre_lit_les_formes_de_l_insee():
    assert fp.nombre(1815.2) == (1815.2, None)
    assert fp.nombre("83") == (83.0, None)
    assert fp.nombre("1\xa0815,2") == (1815.2, None)
    assert fp.nombre("1830,9") == (1830.9, None)


def test_valeur_absente_jamais_zero():
    for brut, mention in (("nd", "nd"), ("///", "///"), ("/", "/"), ("nc", "nc")):
        v, m = fp.nombre(brut)
        assert v is None and m == mention
    assert fp.nombre(None) == (None, "")
    assert fp.montant("/") is None and fp.montant("") is None
    assert fp.montant("0 €") == 0.0  # un zéro publié reste un zéro


def test_montant_euros_pourcentages_et_negatifs():
    assert fp.montant("2 628 066 €") == 2628066.0
    assert fp.montant("-4 601 €") == -4601.0
    assert fp.montant("0,132 %") == 0.132
    assert fp.montant("-1,297%") == -1.297


def test_appel_de_note_retire_du_libelle():
    assert fp.sans_appel_de_note("Secteur communal4") == "Secteur communal"
    assert fp.sans_appel_de_note("Fonction publique territoriale (FPT)3") == "Fonction publique territoriale (FPT)"
    assert fp.sans_appel_de_note("De 15 à 24 ans") == "De 15 à 24 ans"
    assert fp.sans_appel_de_note("2012") == "2012"


# --- Lecture : tableaux de l'Insee -----------------------------------------------------------------------------------

def test_series_insee_deux_versions_et_non_disponible():
    statuts = ["Fonctionnaire et militaires", "Contractuels (hors contrats aidés)", "Bénéficiaires de contrats aidés",
               "Autres catégories et statuts²", "Ensemble"]
    lignes = [
        ["Effectifs dans la fonction publique par versant\net par ministère"], [], ["en milliers"],
        ["Fonction publique", "2023", None, None, None, None, "2023¹ (r)", None, None, None, None, 2024],
        [None] + statuts * 3,
        ["Fonction publique de l'État (FPE)", 10.0, 2.0, 0.5, 1.0, 13.5, "10,1", "2,0", "0,5", "1,0", "13,6", 10.2, 2.1,
         0.4, 1.0, 13.7],
        ["\xa0\xa0\xa0Ministères", 8.0, 1.0, "0", 1.0, 10.0, 8.0, 1.0, "0", 1.0, 10.0, 8.1, 1.0, "0", 1.0, 10.1],
        ["\xa0\xa0\xa0\xa0\xa0\xa0Intérieur et défense", "nd", "nd", "nd", "nd", "nd", 3.0, 0.2, "0", 0.1, 3.3, 3.0, 0.2,
         "0", 0.1, 3.3],
        ["Ensemble (FPE+FPT+FPH)", 10.0, 2.0, 0.5, 1.0, 13.5, 10.1, 2.0, 0.5, 1.0, 13.6, 10.2, 2.1, 0.4, 1.0, 13.7],
        ["nd\xa0: donnée non disponible."], ["Source : Insee, Siasp."],
    ]
    r = fp.lire_series(lignes)
    assert [s["cle"] for s in r["series"]] == ["2023", "2023r", "2024"]
    assert [s["revisee"] for s in r["series"]] == [False, True, False]
    par_id = {l["id"]: l for l in r["lignes"]}
    assert par_id["ministeres"]["niveau"] == "type_employeur"
    assert par_id["ministeres"]["parent"] == "fonction_publique_de_l_etat_fpe"
    d = par_id["interieur_et_defense"]
    assert d["niveau"] == "ministere" and d["parent"] == "ministeres"
    assert d["valeurs"]["ensemble"] == [None, 3.3, 3.3] and d["non_disponible"] == ["2023"]
    assert par_id["ensemble_fpe_fpt_fph"]["niveau"] == "ensemble"
    assert par_id["ministeres"]["valeurs"]["contrats_aides"] == [0.0, 0.0, 0.0]  # zéro publié, pas une absence
    assert r["notes_source"] == ["nd : donnée non disponible.", "Source : Insee, Siasp."]


def test_tableau_insee_entetes_fusionnes_rubriques_et_absences():
    lignes = [
        ["Figure 3 – Caractéristiques des salariés"], [None, None, None, "en %"],
        ["Caractéristiques", "FPE", "FPT", "Ensemble"], ["Statut"],
        ["Fonctionnaires", 58.1, 69.5, "63,8"], ["Militaires", 12.1, "///", 5.3], ["Catégorie1"],
        ["Catégorie A", 54.5, 13.1, 38.4],
        ["///\xa0: absence de résultats due à la nature des choses."], ["Champ : France hors Mayotte."],
    ]
    t = fp.lire_tableau(lignes)
    assert t["titre"] == "Caractéristiques des salariés" and t["unite"] == "en %"
    assert t["colonnes"] == ["FPE", "FPT", "Ensemble"]
    assert t["lignes"][0] == {"rubrique": "Statut", "libelle": "Fonctionnaires", "valeurs": [58.1, 69.5, 63.8]}
    assert t["lignes"][1]["valeurs"] == [12.1, None, 5.3] and t["lignes"][1]["absences"] == {"1": "///"}
    assert t["lignes"][2]["rubrique"] == "Catégorie"
    assert len(t["notes_source"]) == 2


def test_tableau_insee_entete_a_deux_niveaux():
    lignes = [
        ["Figure 1 – Effectifs"],
        ["Versant", "2023", None, "2024", None],
        [None, "Y compris contrats aidés", "Hors contrats aidés", "Y compris contrats aidés", "Hors contrats aidés"],
        [None, "en milliers", None, None, None],
        ["Effectifs au 31 décembre1"], ["Ensemble de la fonction publique", 5843.9, 5815.1, 5876.7, 5850.9],
        ["Source : Insee."],
    ]
    t = fp.lire_tableau(lignes)
    assert t["unite"] == "en milliers"
    assert t["colonnes"][0] == "2023 ; Y compris contrats aidés" and t["colonnes"][3] == "2024 ; Hors contrats aidés"
    assert t["lignes"][0]["rubrique"] == "Effectifs au 31 décembre"


def test_territoires_colonnes_verifiees():
    ent = [None, None, "Ensemble hors militaires (en milliers)",
           "Part des femmes de la fonction publique hors militaires (en %)",
           "Fonction publique de l'État hors militaires (en milliers)", "Fonction publique territoriale (en milliers)",
           "Fonction publique hospitalière (en milliers)",
           "Effectifs de la fonction publique hors militaires pour 100 habitants",
           "Effectifs de la fonction publique hors militaires pour 100 emplois salariés"]
    lignes = [["Effectifs de la fonction publique par versant au 31 décembre 2023 : comparaisons départementales"], [],
              [], ent, ["01", "Ain", 34.5, 71.8, 14.2, 12.9, 7.4, 5.1, 16.5], ["03", "Allier", 27.1, 67.5, 7.8, 9.5, 9.8,
                                                                               8.2, "24"],
              ["Champ : France hors Mayotte."], ["Source : Insee."]]
    t = fp.lire_territoires(lignes)
    assert t["annee"] == 2023 and t["lignes"]["03"]["valeurs"][-1] == 24.0
    ent[4], ent[5] = ent[5], ent[4]
    with pytest.raises(SystemExit):
        fp.lire_territoires(lignes)


# --- Lecture : PDF (mots positionnés) --------------------------------------------------------------------------------

def test_cellules_finissent_au_symbole():
    ws = [mot("2", 220), mot("628", 227), mot("066", 242), mot("€", 258), mot("1", 277), mot("989", 283),
          mot("843", 298), mot("904", 313), mot("€", 328), mot("0,132", 349), mot("%", 369), mot("/", 410),
          mot("-4", 450), mot("601", 462), mot("€", 480), mot("0,138%", 520)]
    assert [c["t"] for c in fp.cellules(ws)] == ["2 628 066 €", "1 989 843 904 €", "0,132 %", "/", "-4 601 €",
                                                 "0,138%"]


def test_ranger_rangee_incomplete_par_ancres():
    def rangee(textes_x1):
        return [{"x0": x1 - 30, "x1": x1, "t": t} if t != "/" else {"x0": x1 - 17, "x1": x1 - 13, "t": "/"}
                for t, x1 in textes_x1]

    cols = [262, 333, 375, 439, 510, 552]
    complete = rangee(list(zip(["1 €", "2 €", "0,1 %", "3 €", "4 €", "0,2 %"], cols)))
    slashs = rangee(list(zip(["/"] * 6, cols)))
    incomplete = rangee([("7 €", 262), ("/", 333), ("-9 €", 439), ("/", 510), ("/", 552)])  # colonne 3 absente
    r = fp.ranger([complete, slashs, incomplete], 6, [])
    assert r[0] == ["1 €", "2 €", "0,1 %", "3 €", "4 €", "0,2 %"]
    assert r[2] == ["7 €", "/", None, "-9 €", "/", "/"]


def test_table_libelle_sur_trois_lignes():
    lignes = [
        [mot("Economie,", 42, 257), mot("finances", 90, 257)],
        [mot("6", 256, 263), mot("819", 262, 263), mot("032", 278, 263), mot("€", 296, 263)],
        [mot("industrielle", 42, 269)],
        [mot("Justice", 42, 290), mot("2", 256, 290), mot("136", 262, 290), mot("647", 278, 290), mot("€", 296, 290)],
        [mot("TOTAL", 42, 320), mot("8", 256, 320), mot("955", 262, 320), mot("679", 278, 320), mot("€", 296, 320)],
    ]
    r = fp.lire_table(lignes, 240, [])
    assert r == [("Economie, finances industrielle", ["6 819 032 €"]), ("Justice", ["2 136 647 €"]),
                 ("TOTAL", ["8 955 679 €"])]


def test_table_programmes_intertitre_et_marges_de_page():
    def ligne(mots_, top):
        x, out = 59.0, []
        for t in mots_:
            out.append(mot(t, x, top))
            x = out[-1]["x1"] + 3
        return out

    def vals(triplets, top):
        return [mot(t, x, top) for t, x in triplets]

    six = [("1", 250), ("€", 258), ("9", 320), ("€", 328), ("0,1", 350), ("%", 369), ("2", 427), ("€", 435),
           ("8", 498), ("€", 506), ("0,2", 527), ("%", 547)]
    flux = [
        ([mot("Ministère", 270, 169), mot("des", 320, 169), mot("armées", 340, 169)], 59.0),
        (ligne(["P.144", "–", "Environnement", "et"], 191), 59.0),
        (vals(six, 197), 59.0),
        (ligne(["de", "la", "défense"], 203), 59.0),
        ([mot("Ministère", 270, 230), mot("de", 320, 230), mot("la", 335, 230), mot("culture", 350, 230)], 59.0),
        # page suivante, marge différente : les lignes à 42 points ne sont pas des intertitres
        ([mot("P.", 42, 100), mot("131", 52, 100), mot("-", 70, 100), mot("Création", 78, 100)] + vals(six, 100), 42.0),
        ([mot("TOTAL", 42, 130)] + vals(six, 130), 42.0),
    ]
    r = fp.lire_table_programmes(flux, 215, [268.0, 334.0, 371.0, 445.0, 511.0])
    assert [lib for lib, _ in r] == ["P.144 – Environnement et de la défense", "P. 131 - Création", "TOTAL"]
    assert r[0][1] == ["1 €", "9 €", "0,1 %", "2 €", "8 €", "0,2 %"]


# --- Cabinets ----------------------------------------------------------------------------------------------------------

JAUNE_CABINETS = """Les cabinets comprenaient 48 membres au 1er juillet 2025.
1. Membres du Cabinet 48
Directeur 3
Directeur-adjoint 4
Chef et chef-adjoint 5
Conseiller et conseiller technique 35
Autres collaborateurs 1
2. Personnels chargés des fonctions support 1 380
Protection du ministre (dont officiers de sécurité) 80
Total général des personnels (1+2) 1 428
Personnels affectés par le ministère 10 1000
Personnels mis à disposition 20 200
Fonctionnaires détachés 2 80
Personnel sur contrat 16 100
Total 48 1380
Cabinets ministériels au 1er juillet 2025
2025 2025 2025
MINISTERES
Affaires étrangères 80 24 56 1 564 000
Ministre de l'Europe et des Affaires étrangères 43 15 28 1 169 000
Ministre délégué chargé du Commerce extérieur et des
37 9 28 395 000
Français de l'Etranger
Agriculturei nette arnliamtieonntaautxion 95 14 81 649 092
Ministre de l'Agriculture et de la Souveraineté alimentaire 95 14 81 649 092
Fonction publique
1 253 10 1 243 404 232
Ministre de l'Action publique, de la Fonction publique, et de la
Simplification 1 253 10 1 243 404 232
Total général 1 428 48 1 380 2 617 324"""


def test_decouper_nombres_avec_espaces_de_milliers():
    assert fp.decouper("2 741 521 2 220 27 361 062".split()) == [2741, 521, 2220, 27361062]
    assert fp.decouper("609 108 501 7 350 000".split()) == [609, 108, 501, 7350000]
    assert fp.decouper("28 9 19 230 000".split()) == [28, 9, 19, 230000]
    assert fp.decouper("28 9 20 230 000".split()) is None  # total différent de membres + support


def test_cabinets_poles_reconnus_par_la_somme_sans_ligne_de_cabinet():
    c = fp.lire_cabinets([JAUNE_CABINETS])
    assert c["annee"] == 2025 and c["date_situation"] == "2025-07-01"
    assert [p["pole"] for p in c["poles"]] == ["Affaires étrangères", "Agriculture et alimentation",
                                               "Fonction publique"]
    assert [p["nb_cabinets"] for p in c["poles"]] == [2, 1, 1] and c["nb_cabinets"] == 4
    assert c["poles"][1]["libelle_restitue"] is True  # textes superposés dans le PDF
    assert c["poles"][2]["effectif_total"] == 1253 and c["poles"][2]["dotation_isp_eur"] == 404232
    assert c["total"] == {"effectif_total": 1428, "membres_cabinet": 48, "fonctions_support": 1380,
                          "dotation_isp_eur": 2617324}
    assert c["par_fonction"]["membres"] == 48 and c["par_fonction"]["fonctions_support"] == 1380
    assert c["par_fonction"]["logistique"] is None  # absent de l'extrait : null, pas 0
    assert c["par_position_statutaire"]["sur_contrat"] == {"membres_cabinet": 16, "fonctions_support": 100}
    assert "Ministre" not in json.dumps(c, ensure_ascii=False)


def test_cabinets_total_incoherent_refuse():
    with pytest.raises(SystemExit):
        fp.lire_cabinets([JAUNE_CABINETS.replace("Total général 1 428 48 1 380 2 617 324",
                                                 "Total général 1 429 48 1 381 2 617 324")])


# --- Conseils ------------------------------------------------------------------------------------------------------------

def test_totaux_conseils_une_ou_deux_tables():
    une = ["Consommation AE 2021 CP 2021 AE 2022 CP 2022 AE S1 2023 CP S1 2023\n"
           "Total 271 486 738 € 234 995 629 € 137 309 881 € 156 322 300 € 35 548 283 € 63 433 798 €"]
    r = {(t["exercice"], t["semestre_1_seul"]): t for t in fp.lire_totaux_conseils(une)}
    assert r[(2021, False)]["ae_eur"] == 271486738.0 and r[(2022, False)]["cp_eur"] == 156322300.0
    assert r[(2023, True)]["ae_eur"] == 35548283.0
    deux = ["Consommation AE 2023 AE 2024\nTotal 73 441 766 € 96 115 562 €\n"
            "Consommation CP 2023 CP 2024\nTotal 87 031 362 € 94 104 817 €"]
    r = {t["exercice"]: t for t in fp.lire_totaux_conseils(deux)}
    assert r[2024] == {"exercice": 2024, "semestre_1_seul": False, "ae_eur": 96115562.0, "cp_eur": 94104817.0}


PAGE_PRESTATAIRES = """Répartition des commandes de conseils extérieurs par titulaire
En 2024, l'État a passé commande de prestations de conseils en stratégie et organisation à 1 728 prestataires
distincts (1 574 tiers siretés et 154 tiers sans Siret). Les vingt prestataires suivants constituent les principaux
fournisseurs sur la période considérée et représentent 44 % des engagements de dépenses pris en compte :
1) UNION DES GROUPEMENTS D'ACHATS PUBLICS (UGAP)
SIREN 776 056 467
4110 - Établissement public national à caractère industriel ou
Catégorie juridique
commercial doté d'un comptable public
Activité principale exercée 46.19A - Centrales d'achat non alimentaires
UNION DES GROUPEMENTS D'ACHATS PUBLICS (UGAP) a fait l'objet de 84 commandes pour un montant total
de 5,4 M€, répartis entre les différents ministères
2) PRESTATAIRE ANONYMISÉ
Le ministère des armées a fait valoir que le détail de ces informations nécessiterait une diffusion restreinte.
3) JEANNE MARTIN CONSEIL
SIREN 123 456 789
Catégorie juridique 1000 - Entrepreneur individuel
Activité principale exercée 70.22Z - Conseil pour les affaires
JEANNE MARTIN CONSEIL a fait l'objet d'une commande pour un montant total de 1,3 M :
4) CABINET EXEMPLE ET ASSOCIES
SIREN 388 125 924
Catégorie juridique 5710 - SAS, société par actions simplifiée
CABINET EXEMPLE ET ASSOCIES a fait l'objet de 4 commandes pour un montant total de 1,2 M€ :"""


def test_prestataire_nomme_seulement_si_personne_morale():
    r = fp.lire_prestataires([PAGE_PRESTATAIRES])
    assert r["periode"] == "2024" and r["nb_prestataires_distincts"] == 1728
    assert r["part_des_vingt_premiers_pct"] == 44
    l = r["lignes"]
    assert l[0]["denomination"].startswith("UNION DES GROUPEMENTS") and l[0]["categorie_juridique"] == "4110"
    assert l[0]["siren"] == "776056467" and l[0]["nb_commandes"] == 84 and l[0]["montant_meur"] == 5.4
    assert l[1]["denomination"] is None and l[1]["motif_non_nomme"] == "anonymisé par la source"
    assert l[1]["montant_meur"] is None  # non publié : null, pas 0
    # entrepreneur individuel : ni nom, ni SIREN, ni catégorie ; le montant reste
    assert l[2]["denomination"] is None and l[2]["siren"] is None and l[2]["categorie_juridique"] is None
    assert l[2]["montant_meur"] == 1.3 and l[2]["nb_commandes"] == 1
    assert "JEANNE" not in json.dumps(r, ensure_ascii=False)
    assert l[3]["denomination"] == "CABINET EXEMPLE ET ASSOCIES" and l[3]["categorie_juridique"] == "5710"


def test_prestataires_periode_cumulee():
    t = PAGE_PRESTATAIRES.replace("En 2024, l'État a passé commande", "Entre le 1er janvier 2022 et le 31 décembre "
                                  "2023, l'État a passé commande")
    assert fp.lire_prestataires([t])["periode"] == "2022-2023"


def test_fusion_conseils_edition_recente_et_ecart_publie():
    def edition(ae23, complet=True):
        e = {"totaux": [{"exercice": 2023, "semestre_1_seul": False, "ae_eur": ae23, "cp_eur": 5.0}]}
        if complet:
            e.update({"ministeres": {"2023": {"nomenclature": "format LFI 2023", "total_ae_eur": ae23,
                                              "somme_des_lignes_ae_eur": ae23, "lignes": []}},
                      "missions": {"annees": [2023], "total_ae_eur": [ae23], "lignes": []},
                      "programmes": {"annees": ["2023"], "total_ae_eur": {"2023": ae23},
                                     "somme_programmes_ae_eur": {"2023": ae23},
                                     "programmes": {"144": {"programme": "144", "libelle": "X", "exercices": {
                                         "2023": {"ae_consommees_eur": ae23, "ae_ouvertes_lfi_eur": 100.0,
                                                  "part_pct": 1.0}}}}},
                      "prestataires": {}})
        return e

    r = fp.fusion_conseils({2024: edition(9.0, complet=False), 2025: edition(10.0), 2026: edition(12.0)})
    t = r["totaux"][0]
    assert t["edition_retenue"] == "PLF 2026" and t["ae_eur"] == 12.0 and t["editions_concordantes"] is False
    assert t["editions"]["PLF 2025"]["ae_eur"] == 10.0  # l'écart reste publié
    ex = r["par_programme"][0]["exercices"]["2023"]
    assert ex["edition"] == "PLF 2026" and ex["edition_precedente"] == {"edition": "PLF 2025",
                                                                        "ae_consommees_eur": 10.0}
    assert r["par_ministere"]["2023"]["edition"] == "PLF 2026"


# --- Barème des élus ---------------------------------------------------------------------------------------------------

def test_rangee_bareme_lecture_verifiee_par_le_taux():
    base = 4110.52
    assert fp.rangee_bareme("De 3 500 à 9 999 22 904,32", base) == ("De 3 500 à 9 999", 22.0, 904.32, True)
    assert fp.rangee_bareme("De 3 500 à 9 999 55 2 260,79", base) == ("De 3 500 à 9 999", 55.0, 2260.79, True)
    assert fp.rangee_bareme("28 1 150,95", base) == ("", 28.0, 1150.95, True)
    assert fp.rangee_bareme("Moins de 500 25,5 1 048,18", base) == ("Moins de 500", 25.5, 1048.18, True)
    assert fp.rangee_bareme("Moins de 500 25,5 1 000,00", base)[3] is False
    assert fp.rangee_bareme("Décret n° 2023-519 du 28 juin 2023", base) is None


def test_bareme_fonctions_strates_et_rangee_fausse_ecartee():
    page = """ANNEXE 1
INDEMNITÉS DE FONCTION BRUTES MENSUELLES DES MAIRES
(VALEUR DU POINT D'INDICE AU 1er janvier 2024)
Art. L. 2123-23 du code général des collectivités territoriales
POPULATION TAUX INDEMNITÉ BRUTE
Moins de 500 25,5 1 048,18
De 3 500 à 9 999 55 2 260,79
De 500 à 999 40,3 9 999,99
INDEMNITÉS DE FONCTION BRUTES MENSUELLES DES CONSEILLERS MUNICIPAUX
Communes de 100 000 habitants et plus :
6 246,63
conseillers municipaux (art. L. 2123-24-1-I du CGCT)
Montant mensuel correspondant à l'indice brut 1027 au 1er janvier 2024 : 4 110,52 €
Décret n° 2023-519 du 28 juin 2023"""
    b = fp.lire_bareme([page])
    assert b["indice_brut_1027_mensuel_eur"] == 4110.52 and b["date_valeur"] == "1er janvier 2024"
    assert b["rangees_ecartees"] == 1
    assert [(l["fonction"], l["strate"], l["taux_pct_ib1027"]) for l in b["lignes"]] == [
        ("Maires", "Moins de 500", 25.5), ("Maires", "De 3 500 à 9 999", 55.0),
        ("Conseillers municipaux", "Communes de 100 000 habitants et plus : conseillers municipaux (art. L. "
         "2123-24-1-I du CGCT)", 6.0)]
    assert b["lignes"][0]["base_legale"].startswith("Art. L. 2123-23")


# --- Rapprochement sans double compte ----------------------------------------------------------------------------------

def test_rapprochement_un_programme_un_seul_ministere():
    eff = {p: {"libelle": f"Programme {p}", "etpt": e, "titre2_eur": t}
           for p, e, t in (("140", 100.0, 1000.0), ("141", 50.0, 500.0), ("166", 10.0, None), ("200", None, 7.0))}
    mins = {"140": "Éducation nationale et jeunesse", "141": "Éducation nationale et jeunesse", "166": "Justice"}
    cons_prog = {"140": {"exercices": {"2024": {"ae_consommees_eur": 3.0}}}}
    cons_min = {"2024": {"lignes": [{"ministere": "Justice", "ae_eur": 9.0},
                                    {"ministere": "Crédits interministériels", "ae_eur": 4.0}]}}
    cab = [{"annee": 2025, "poles": [{"pole": "Justice", "ministeres_budget": ["justice"]}]}]
    insee = {"colonnes": ["2023", "2024", "Évolution"], "lignes": [
        {"libelle": "Justice", "valeurs": [92.6, 94.6, 2.2]},
        {"libelle": "Armées (militaires)", "valeurs": [209.4, 211.0, 0.8]},
        {"libelle": "Armées (personnels civils)", "valeurs": [66.5, 68.2, 2.4]}]}
    r = fp.rapprocher(mins, eff, {"140": {"noeud": "A/B/140", "fichier": "arbre/x_140.json"}}, cons_prog, cons_min,
                      cab, insee)
    par_id = {m["id"]: m for m in r["ministeres"]}
    edu = par_id["education_nationale_et_jeunesse"]
    assert edu["etpt"] == 150.0 and edu["titre2_eur"] == 1500.0 and edu["nb_programmes"] == 2
    assert edu["programmes"][0]["conseils_ae_consommees_eur"] == {"2024": 3.0}
    assert edu["programmes"][0]["fichier_arbre"] == "arbre/x_140.json" and edu["programmes"][1]["fichier_arbre"] is None
    j = par_id["justice"]
    assert j["titre2_eur"] is None and j["programmes_sans_titre2"] == ["166"]  # non publié : null, pas 0
    assert j["conseils_ae_eur"] == {"2024": 9.0} and j["poles_cabinets"] == {"2025": ["Justice"]}
    assert [p["programme"] for p in r["programmes_sans_ministere"]] == ["200"]
    tous = [p["programme"] for m in r["ministeres"] for p in m["programmes"]] + ["200"]
    assert sorted(tous) == sorted(eff) and len(set(tous)) == len(tous)
    assert r["conseils_hors_nomenclature"]["2024"] == [{"ministere": "Crédits interministériels", "ae_eur": 4.0}]
    armees = next(g for g in r["groupes_insee"] if g["ministeres_budget"] == ["armees"])
    assert armees["effectif_milliers"] == {"2023": 275.9, "2024": 279.2}  # deux lignes disjointes du même tableau
    eco = next(g for g in r["groupes_insee"] if g["groupe_insee"] == "Économie et finances")
    assert eco["effectif_milliers"] is None  # ligne absente de l'extrait : null


def test_groupes_insee_chaque_ministere_dans_un_seul_groupe():
    ids = [i for _, _, m in fp.GROUPES_INSEE for i in m]
    assert len(ids) == len(set(ids))
    assert set(i for v in fp.POLES_MINISTERES.values() for i in v) <= set(ids)


# --- Sorties publiées ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("nom", FICHIERS)
def test_entete_et_taille(nom):
    d = charger(nom)
    assert d["millesime"] and d["source"].count("http") >= 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"])
    assert (FP / f"{nom}.json").stat().st_size < 5_000_000


def test_index_renvoie_a_tous_les_fichiers():
    idx = charger("index")
    assert sorted(f["fichier"] for f in idx["fichiers"]) == sorted(f"fonction_publique/{n}.json" for n in FICHIERS
                                                                   if n != "index")
    for f in idx["fichiers"]:
        assert (DATA / f["fichier"]).exists()
    assert {r["verdict"] for r in idx["recherche_prealable"]} <= {"réutilisable tel quel", "à adapter",
                                                                  "inspiration seulement"}


def test_series_versants_somment_a_l_ensemble():
    d = charger("effectifs_series")
    lignes = {l["id"]: l for l in d["lignes"]}
    versants = [l for l in d["lignes"] if l["niveau"] == "versant"]
    ens = next(l for l in d["lignes"] if l["niveau"] == "ensemble")
    assert len(versants) == 3 and len(d["series"]) >= 14
    for st in ("ensemble", "contractuels"):
        for k, s in enumerate(d["series"]):
            somme = sum(v["valeurs"][st][k] for v in versants)
            assert abs(somme - ens["valeurs"][st][k]) <= 0.31, (st, s["cle"])
    for l in d["lignes"]:
        assert l["parent"] is None or l["parent"] in lignes
        for vals in l["valeurs"].values():
            assert len(vals) == len(d["series"])
        nuls = {d["series"][k]["cle"] for k, v in enumerate(l["valeurs"]["ensemble"]) if v is None}
        assert nuls == set(l["non_disponible"])  # toute valeur absente porte sa mention


def test_series_types_d_employeur_somment_au_versant():
    d = charger("effectifs_series")
    k = len(d["series"]) - 1
    for v in (l for l in d["lignes"] if l["niveau"] == "versant"):
        enfants = [l for l in d["lignes"] if l["parent"] == v["id"]]
        assert enfants
        assert abs(sum(e["valeurs"]["ensemble"][k] for e in enfants) - v["valeurs"]["ensemble"][k]) <= 0.31


def test_territoires_departements_somment_a_la_france():
    d = charger("territoires")
    assert len(d["departements"]) == 100 and len(d["regions"]) == 17
    fr = d["ensembles"]["france_hors_mayotte"]["valeurs"]
    for k in (0, 2, 3, 4):  # effectifs en milliers
        assert abs(sum(v["valeurs"][k] for v in d["departements"].values()) - fr[k]) <= 3.0
        assert abs(sum(v["valeurs"][k] for v in d["regions"].values()) - fr[k]) <= 1.0
    for v in d["departements"].values():
        e, fpe, fpt, fph = (v["valeurs"][k] for k in (0, 2, 3, 4))
        assert abs(fpe + fpt + fph - e) <= 0.21, v["libelle"]


def test_cabinets_poles_somment_au_total_et_aucun_cabinet_nomme():
    d = charger("cabinets")
    assert [s["annee"] for s in d["situations"]] == sorted(s["annee"] for s in d["situations"])
    for s in d["situations"]:
        for c in ("effectif_total", "membres_cabinet", "fonctions_support", "dotation_isp_eur"):
            assert sum(p[c] for p in s["poles"]) == s["total"][c], (s["annee"], c)
        assert s["total"]["effectif_total"] == s["total"]["membres_cabinet"] + s["total"]["fonctions_support"]
        assert s["par_fonction"]["total"] == s["total"]["effectif_total"]
        assert s["par_position_statutaire"]["total"]["membres_cabinet"] == s["total"]["membres_cabinet"]
        for p in s["poles"]:
            assert p["effectif_total"] == p["membres_cabinet"] + p["fonctions_support"]
            assert not re.match(r"(?i)(ministre|secrétaire d|garde des sceaux)", p["pole"]), p["pole"]
    assert not re.search(r"\bM(\.|me|adame|onsieur) [A-ZÉ]", json.dumps(d, ensure_ascii=False))


def test_conseils_sommes_et_totaux_publies():
    d = charger("conseils")
    for an, b in d["par_ministere"].items():
        assert abs(sum(l["ae_eur"] for l in b["lignes"]) - b["total_ae_eur"]) <= len(b["lignes"]), an
    m = d["par_mission"]
    for k, an in enumerate(m["annees"]):
        assert abs(sum(l["ae_eur"][k] or 0 for l in m["lignes"]) - m["total_ae_eur"][k]) <= len(m["lignes"]), an
    for cle, c in d["controle_programmes"].items():
        assert c["total_publie_ae_eur"] is not None, cle
        assert abs(c["somme_des_programmes_lus_ae_eur"] - c["total_publie_ae_eur"]) <= 200, cle
    tot = {(t["exercice"], t["semestre_1_seul"]): t for t in d["totaux"]}
    for an, b in d["par_ministere"].items():
        assert b["total_ae_eur"] == tot[(int(an), False)]["ae_eur"]  # même total dans les deux tables du jaune
    progs = [p["programme"] for p in d["par_programme"]]
    assert progs == sorted(set(progs))


def test_conseils_prestataires_personnes_morales_seulement():
    d = charger("conseils")
    import sirene
    assert d["prestataires"]
    for periode, b in d["prestataires"].items():
        assert [l["rang"] for l in b["lignes"]] == list(range(1, len(b["lignes"]) + 1))
        for l in b["lignes"]:
            if l["denomination"] is None:
                assert l["siren"] is None and l["categorie_juridique"] is None and l["motif_non_nomme"]
            else:
                assert sirene.personne_morale(l["categorie_juridique"]) and sirene.siren_valide(l["siren"]), l


def test_bareme_montant_egal_taux_fois_indice():
    d = charger("indemnites_elus")
    base = d["indice_brut_1027_mensuel_eur"]
    assert len(d["lignes"]) >= 80
    for l in d["lignes"]:
        assert abs(l["taux_pct_ib1027"] * base / 100 - l["indemnite_brute_mensuelle_eur"]) <= 0.011, l
    assert {"Maires", "Adjoints au maire", "Conseillers départementaux", "Conseillers régionaux"} <= {
        l["fonction"] for l in d["lignes"]}
    maires = [l for l in d["lignes"] if l["fonction"] == "Maires"]
    assert maires[0]["strate"] == "Moins de 500" and maires[0]["taux_pct_ib1027"] == 25.5


def test_ministeres_sans_double_compte_et_coherents_avec_effectifs():
    d = charger("ministeres")
    progs = [p for m in d["ministeres"] for p in m["programmes"]] + d["programmes_sans_ministere"]
    codes = [p["programme"] for p in progs]
    assert len(codes) == len(set(codes)), "un programme compté dans deux ministères"
    publies = sorted(f.stem for f in (DATA / "effectifs").glob("*.json"))
    assert sorted(codes) == publies  # tous les programmes de site/data/effectifs, une fois chacun
    for p in progs:
        e = json.loads((DATA / p["fichier_effectifs"]).read_text(encoding="utf-8"))
        assert p["etpt"] == e["etpt"] and p["titre2_eur"] == e["titre2_eur"], p["programme"]  # repris, pas recalculés
        assert p["fichier_arbre"] is None or (DATA / p["fichier_arbre"]).exists()
    for m in d["ministeres"]:
        assert abs(m["etpt"] - sum(p["etpt"] or 0 for p in m["programmes"])) < 0.01
        assert abs((m["titre2_eur"] or 0) - sum(p["titre2_eur"] or 0 for p in m["programmes"])) < 0.01
    assert abs(d["totaux"]["etpt"] - sum(m["etpt"] for m in d["ministeres"])) < 0.01
    total_site = sum(json.loads(f.read_text(encoding="utf-8"))["titre2_eur"] or 0
                     for f in (DATA / "effectifs").glob("*.json"))
    assert abs(d["totaux"]["titre2_eur"] + d["totaux"]["titre2_programmes_sans_ministere_eur"] - total_site) < 1


def test_ministeres_groupes_insee_couvrent_chaque_ministere_une_fois():
    d = charger("ministeres")
    ids = [i for g in d["groupes_insee"] for i in g["ministeres_budget"]]
    assert sorted(ids) == sorted(m["id"] for m in d["ministeres"])
    assert abs(sum(g["etpt_ministeres_budget"] for g in d["groupes_insee"]) - d["totaux"]["etpt"]) < 0.01
    for m in d["ministeres"]:
        assert m["groupe_insee"] in {g["groupe_insee"] for g in d["groupes_insee"]}


def test_ecarts_entre_sources_publies_sans_arbitrage():
    idx = charger("index")
    assert idx["ecarts_entre_sources"]
    for e in idx["ecarts_entre_sources"]:
        assert len(e["valeurs"]) >= 2 and all(v["source"] for v in e["valeurs"])
        assert not {"retenu", "retenue", "valeur_retenue"} & set(e)
    serie = charger("effectifs_series")
    ens = next(l for l in serie["lignes"] if l["niveau"] == "ensemble")
    assert idx["reperes"]["effectifs"]["ensemble"] == ens["valeurs"]["ensemble"][-1]


def test_aucune_personne_physique_dans_les_sorties():
    interdites = {"nom", "prenom", "prénom", "civilite", "adresse", "courriel", "email", "telephone", "dirigeant",
                  "responsable", "ministre", "elu", "auteur"}

    def cles(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from cles(v)
        elif isinstance(x, list):
            for v in x:
                yield from cles(v)

    for nom in FICHIERS:
        d = charger(nom)
        assert not interdites & set(cles(d)), nom
        assert "CHUNG" not in json.dumps(d, ensure_ascii=False)  # auteur des métadonnées du PDF, jamais repris
