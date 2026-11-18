"""Énergie et climat (pipeline/energie_climat.py) : lecture des tableaux de la CRE, règles du module et cohérence des
fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "energie_climat"
sys.path.insert(0, str(ROOT / "pipeline"))
import energie_climat as ec  # noqa: E402

# Extraits de `pdftotext -layout` des délibérations n° 2026-149 (avec sous-total) et 2024-139 (sans sous-total).
TABLEAU_2026 = """Le tableau ci-dessous présente, par action 13, les charges au titre des années 2025 à 2027, évaluées
dans le cadre de la présente délibération, ainsi que, à des fins de comparaison, le niveau des charges
constatées au titre de 2024.
Tableau 3 : Tableau récapitulatif des charges par action au titre des années 2024 à 2027
                                                                         Charges         Charges      Mise à jour de la        Charges
                                                                      constatées au   constatées au   prévision au titre prévisionnelles au
                                                              en M€   titre de 2024   titre de 2025       de 2026          titre de 2027
                               1. Eolien terrestre                         -68,9           901,5           1 157,1             1 404,6
                               2. Eolien en mer                            227,7           655,8            965,6              1 306,7
 1. Soutien ENR électriques 3. Photovoltaïque                            2 408,5         3 755,7          4 125,5             4 579,2
        en métropole           4. Bio-énergies                            394,0           739,0            827,3               855,1
                               5. Autres énergies                         -61,0           129,1            211,0               232,9
                                               TOTAL                    2 900,3         6 181,0           7 286,6            8 378,5
2. Injection biométhane                                                 1 029,3         1 151,4           1 109,8            1 373,3
                               1. Transition énergétique                 1 211,9         1 495,2          1 866,0             2 220,6
      3. Soutien en ZNI        2. Mécanismes de solidarité               1 258,3         1 682,1          1 402,9             1 291,9
                                               TOTAL                    2 470,2         3 177,3           3 268,9            3 512,5
4. Cogénération et autres moyens thermiques                              354,9           684,7             653,1              600,7
5. Effacement                                                            189,0           126,4             149,7               91,6
                               1. Compensation FSL                        28,5            28,9              31,2               31,4
                               2. Afficheur déporté                       1,4             0,9               2,9                3,6
    6. Dispositifs sociaux
                               3. Autres                                  3,1             3,2               3,8                3,9
                                               TOTAL                      33,0           33,0              37,9               38,9
7. Frais divers                1. Frais de gestion                        97,6          109,6             126,7              132,6
                   Sous total hors BT et amo.                           7 074,3        11 463,3          12 632,8           14 128,2
                               1. Mesures à destination des
                                                                         149,2             0,0              0,0                 0,0
 8. Mesures exceptionnelles consommateurs d'électricité
      de protection des        2. Mesures à destination des
                                                                           0,0             0,0              0,0                 0,0
       consommateurs           consommateurs de gaz
                                               TOTAL                     149,2            0,0               0,0                 0,0
                            TOTAL                                       7223,5*        11 463,3          12 632,8           14 128,2
* Le calcul des charges au titre de 2024 se base sur des prix de marché significativement plus élevés que pour le
calcul des charges au titre des années suivantes, du fait notamment des volumes vendus à terme au titre de l’année
de livraison 2024 durant la crise des prix de l’énergie.
Les charges constatées au titre de 2025 s’élèvent ainsi à 11 463,3 M€. Ce montant est inférieur de
- 169,3 M€ par rapport à la mise à jour de la prévision effectuée en juillet 2025, en raison principalement
d’une sur-prévision des volumes d’énergie renouvelable électrique soutenus en France hexagonale
(partiellement compensée par la hausse du surcoût unitaire 14) et des volumes soutenus en ZNI (cf."""

TABLEAU_2024 = """Tableau récapitulatif des charges par action au titre des années 2022 à 2025
                                                                                                                               Charges prévisionnelles
                                                                             Charges constatées au   Charges constatées au                              Charges prévisionnelles
                                                                                                                               mises à jour au titre de
                                                                                 titre de 2022           titre de 2023                                     au titre de 2025
                                                                     en M€                                                              2024
                                               1. Eolien terrestre                  -2 317,0                 -3 422,6                    -250,8                     233,7
                                               2. Eolien en mer                       -15,2                    -36,4                     241,5                      595,9
                  1. Soutien ENR               3. Photovoltaïque                    1 104,3                   -156,1                    2 187,0                    2 853,4
                  électrique en métropole      4. Bio-énergies                       -118,8                     0,8                      385,6                      570,6
                                               5. Autres énergies                    -507,8                   -380,5                      -38,7                      81,4
                                                         TOTAL                     -1 854,5                 -3 994,9                   2 524,6                    4 335,0
                  2. Injection biométhane                                            78,7                     787,6                    1 061,8                    1 182,4
                                               1. Transition énergétique             547,9                    846,4                     1 164,0                    1 433,4
                  3. Soutien en ZNI         2. Mécanismes de
                                                                                    1 938,2                   1 582,8                   1 261,8                    1 567,2
                                            solidarité
                                                       TOTAL                       2 486,0                   2 429,2                   2 425,8                    3 000,6
                  4. Cogénération et autres moyens thermiques                       659,9                     -252,3                    299,7                      553,3
                  5. Effacement                                                      72,0                      14,4                     198,7                      316,0
                                            1. Compensation FSL                      24,9                      26,1                       28,2                       26,5
                                            2. Afficheur déporté                      1,8                       4,1                        6,2                        6,1
                  6. Dispositifs sociaux
                                            3. Autres                                 7,7                       7,3                        7,0                        7,2
                                                       TOTAL                         34,4                      37,5                      41,4                       39,7
                  7. Frais divers           1. Frais de gestion                      65,4                      85,0                      94,5                       99,1
                  8. Mesures                   1. Electricité                        825,9                   20 162,0                    356,4                       0,0
                  exceptionnelles de
                                               2. Gaz                               3 154,7                   1 335,6                     0,0                        0,0
                  protection des
                  consommateurs                          TOTAL                     3 980,6                  21 497,6                     356,4                       0,0
                                           Total                                   5 522,6                  20 604,1                   7 002,9                    9 526,0"""


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_tableau_2026_lu_et_controle():
    t = ec.lire_tableau_cre(TABLEAU_2026)
    assert t["annees"] == [2024, 2025, 2026, 2027]
    assert not t["sous_total_recalcule"]
    lg = t["lignes"]
    assert set(lg) == set(ec.CLES_CRE)
    assert lg["total"] == [7223.5, 11463.3, 12632.8, 14128.2]
    assert lg["photovoltaique"][0] == 2408.5 and lg["eolien_terrestre"][0] == -68.9
    assert lg["zni_solidarite"] == [1258.3, 1682.1, 1402.9, 1291.9]
    assert lg["mesures_electricite"] == [149.2, 0.0, 0.0, 0.0]


def test_tableau_2024_sans_sous_total_recalcule():
    t = ec.lire_tableau_cre(TABLEAU_2024)
    assert t["annees"] == [2022, 2023, 2024, 2025]
    assert t["sous_total_recalcule"]
    lg = t["lignes"]
    assert lg["total"][1] == 20604.1 and lg["mesures_exceptionnelles"][1] == 21497.6
    assert lg["mesures_gaz"][0] == 3154.7
    # sous-total recalculé comme somme des lignes : à l'arrondi près de « total moins mesures exceptionnelles »
    assert abs(lg["sous_total_hors_mesures"][0] - (lg["total"][0] - lg["mesures_exceptionnelles"][0])) <= 0.15


def test_total_faux_rejete():
    with pytest.raises(ValueError):
        ec.lire_tableau_cre(TABLEAU_2026.replace("14 128,2", "14 228,2", 1))
    with pytest.raises(ValueError):
        ec.lire_tableau_cre("aucun tableau ici")


def test_budget_vert_colonnes_et_retraitements():
    lignes = [
        {"type_depense": "Crédits budgétaires", "numero_programme": 174.0, "code_action": "174-02",
         "code_depense": "174-02-02", "libelle": "Chèque énergie", "action_si_credit_budgetaire": "Accompagnement",
         "execution_2023_cp": 1325768332.57, "lfi_2024_cp_ou_prevision_2024_si_depense_fiscale": 795494265.0,
         "plf_2025_cp_ou_prevision_2025_si_depense_fiscale": None},
        {"type_depense": "Crédits budgétaires", "numero_programme": 345.0, "code_action": "MP/MT - PLF 2025",
         "code_depense": "MP/MT - PLF 2025", "libelle": "MP/MT", "execution_2023_cp": -1.0,
         "lfi_2024_cp_ou_prevision_2024_si_depense_fiscale": 0, "plf_2025_cp_ou_prevision_2025_si_depense_fiscale": 0},
        {"type_depense": "Dépenses fiscales", "numero_programme": 174.0, "execution_2023_cp": 5.0},
        {"type_depense": "Crédits budgétaires", "numero_programme": 102.0, "execution_2023_cp": 5.0},
    ]
    out = ec.lire_budget_vert(2025, lignes)
    assert len(out) == 2
    ch = [l for l in out if ec.est_cheque_energie(l)]
    assert len(ch) == 1 and ch[0]["execution"] == {"annee": 2023, "eur": 1325768332.57}
    assert ch[0]["plf"] == {"annee": 2025, "eur": None} and ch[0]["source_plf"] == 2025
    assert [l["retraitement"] for l in out if l["programme"] == "345"] == [True]
    tot = {(t["programme"], t["annee"], t["nature"]): t for t in ec.totaux_budget(out)}
    assert tot[("345", 2023, "execution")]["hors_retraitements_eur"] == 0.0
    assert tot[("345", 2023, "execution")]["avec_retraitements_eur"] == -1.0
    assert tot[("174", 2025, "plf")]["lignes_null"] == 1


def test_ecart_null_si_une_valeur_manque():
    assert ec._ecart(110.0, 100.0) == {"ecart_m_eur": 10.0, "ecart_pct": 10.0}
    assert ec._ecart(None, 100.0) is None and ec._ecart(1.0, None) is None


def test_sources_documentees():
    for cle, s in ec.SOURCES.items():
        assert s["url"].startswith("https://") and s["page"].startswith("https://"), cle
        assert s["licence"] and s["producteur"] and s["millesime"] and s["verdict"], cle
    assert any("département" in i["source"] for i in ec.INACCESSIBLES)
    assert {c for c, *_ in ec.LIGNES_CRE} == set(ec.CLES_CRE)


# --- fichiers publiés --------------------------------------------------------------------------------------------------

fichiers = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                              reason="site/data/energie_climat absent : lancer `python pipeline/energie_climat.py produire`")


def charger(nom):
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


@fichiers
def test_index_fichiers_et_liens_existent():
    idx = charger("index.json")
    for rel in idx["fichiers"].values():
        assert (SITE / rel).exists(), rel
    for l in idx["liens"]:
        assert (SITE / l["fichier"]).exists(), l["fichier"]
    assert idx["chiffres_cles"] and all(c["m_eur"] is not None for c in idx["chiffres_cles"])


@fichiers
def test_series_reprennent_chaque_evaluation():
    doc = charger("charges_service_public.json")
    for ev in doc["evaluations"]:
        for j, col in enumerate(ev["colonnes"]):
            for cle, vals in ev["lignes"].items():
                serie = doc["series"][str(col["annee"])]["lignes"][cle]
                assert any(v["deliberation"] == ev["deliberation"] and v["m_eur"] == vals[j] for v in serie)
    for an, s in doc["series"].items():
        dates = [v["date"] for v in s["lignes"]["total"]]
        assert dates == sorted(dates), an


@fichiers
def test_boucliers_comparaison_recalculable():
    doc = charger("boucliers.json")
    for c in doc["comparaison"]:
        if c["cre_m_eur"] is None or c["budget_execution_m_eur"] is None:
            assert c["ecart_m_eur"] is None
        else:
            assert abs(c["cre_m_eur"] - c["budget_execution_m_eur"] - c["ecart_m_eur"]) < 0.11
    for b in doc["budget_action_345_17"]:
        assert abs(sum(l["eur"] for l in b["lignes"]) - b["total_eur"]) < 1
        assert abs(sum(l["eur"] for l in b["lignes"] if l["champ_cre"]) - b["hors_carburants_eur"]) < 1


@fichiers
def test_cheque_energie_departements_non_publies_jamais_zero():
    doc = charger("cheque_energie.json")
    assert doc["departements"] is None and doc["departements_mention"]
    assert doc["national"]


@fichiers
def test_aucun_operateur_nomme():
    texte = (DOSSIER / "charges_service_public.json").read_text(encoding="utf-8")
    for nom in ("EDF", "Engie", "ENGIE", "TotalEnergies"):
        assert nom not in texte
