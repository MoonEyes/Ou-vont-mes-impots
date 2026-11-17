"""Tests unitaires (entrées construites à la main) des montants et signes de pipeline/decisions.py."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import decisions as d  # noqa: E402


@pytest.mark.parametrize("brut,attendu", [
    ("89 753 974", 89753974.0), ("89 753 974", 89753974.0), ("-3000000", -3000000.0),
    ("+ 1 000", 1000.0), ("1,5", 1.5), ("− 12", -12.0), ("– 7", -7.0), ("", 0.0), (None, 0.0),
    (12, 12.0), ("1,27055E+11", 127055000000.0), ("-2,5e3", -2500.0), ({"@xsi:nil": "true"}, 0.0),
    # valeur non vide illisible : None, jamais 0
    ("texte", None), ("1.234.567", None), ("12 €", None), ("1,2,3", None), (float("nan"), None),
])
def test_montant(brut, attendu):
    assert d.montant(brut) == attendu


def test_lecture_montant_raison_et_precision():
    assert d.lecture_montant("") == (0.0, None) and d.lecture_montant("89 753 974") == (89753974.0, None)
    v, remarque = d.lecture_montant("1,27055E+11")
    assert v == 127055000000.0 and "6 chiffres significatifs" in remarque and "1,27055E+11" in remarque
    v, raison = d.lecture_montant("n.c.")
    assert v is None and "illisible" in raison and "n.c." in raison
    with pytest.raises(SystemExit):
        d.montant_strict("abc", "test")
    with pytest.raises(SystemExit):
        d.ae_cp({"creditPaiement": "mille"}, "creditPaiement")


def _plrg(tmp_path, monkeypatch, lignes):
    f = tmp_path / "annexe.csv"
    entete = "Mission;Programme;Titre;LFI;LFR;Report_N-1;Mvts_reglementaires;FDC_et_ADP;Total_CP_Ouverts;Depenses_constatees"
    f.write_text("\n".join([entete, *lignes]) + "\n", encoding="utf-8")
    monkeypatch.setattr(d, "_plrg_fichiers", lambda: {2023: f})
    return d.lire_plrg()[2023]


def test_lire_plrg_notation_scientifique_additionnee(tmp_path, monkeypatch):
    """Cas du programme 200 en 2023 : la ligne « autres titres » est en notation scientifique."""
    P = _plrg(tmp_path, monkeypatch, ["M;Remboursements - 200;Titre 2;0;0;0;0;0;0;279,28",
                                      "M;Remboursements - 200;Autres;1,27055E+11;12489402462;0;0;0;1,39544E+11;1,37322E+11"])
    x = P["200"]
    assert x["lfi"] == 127055000000.0 and x["ouverts"] == 139544000000.0 and x["depenses"] == 137322000279.28
    assert x["illisibles"] == {} and set(x["precision"]) == {"lfi", "ouverts", "depenses"}
    b = d.bloc_plrg(x, 2023)
    assert b["depenses_cp"] == 137322000279.28 and set(b["precision_plrg"]) == {"lfi_cp", "ouverts_cp", "depenses_cp"}
    assert "valeurs_illisibles_plrg" not in b
    assert [e["cp"] for e in d.etapes_plrg(x, 2023)] == [127055000000.0, 12489402462.0, 137322000279.28]


def test_lire_plrg_valeur_illisible_null_avec_raison(tmp_path, monkeypatch):
    P = _plrg(tmp_path, monkeypatch, ["M;Prog - 101;Titre 2;1 000;0;0;0;0;1 000;900",
                                      "M;Prog - 101;Autres;#REF!;0;0;n.d.;0;2 000;100"])
    x = P["101"]
    assert x["lfi"] is None and x["mouvements_reglementaires"] is None and x["depenses"] == 1000.0
    b = d.bloc_plrg(x, 2023)
    assert b["lfi_cp"] is None and "#REF!" in b["valeurs_illisibles_plrg"]["lfi_cp"]
    etapes = d.etapes_plrg(x, 2023)
    assert etapes[0]["cp"] is None and "illisible" in etapes[0]["raison"]
    coh = d.coherence([], {2023: P})["2023"]["mouvements_reglementaires"]
    e = coh["ecarts"][0]
    assert e["plrg_cp"] is None and e["conforme"] is None and "illisible" in e["raison"] and coh["programmes_conformes"] == 0


def test_lire_plrg_colonne_absente_arrete(tmp_path, monkeypatch):
    f = tmp_path / "a.csv"
    f.write_text("Mission;Programme;LFI\nM;P - 101;1\n", encoding="utf-8")
    monkeypatch.setattr(d, "_plrg_fichiers", lambda: {2023: f})
    with pytest.raises(SystemExit):
        d.lire_plrg()


def test_nil_et_listify():
    assert d.nil(None) and d.nil({"@xsi:nil": "true"}) and not d.nil({})
    assert d.listify(None) == [] and d.listify({"@xsi:nil": "true"}) == []
    assert d.listify("a") == ["a"] and d.listify([1, 2]) == [1, 2]


def test_ae_cp_plf_et_plfr():
    assert d.ae_cp({"creditPaiement": "1 000"}, "creditPaiement") == 1000.0
    # PLFR : supplémentaire moins annulé (l'annulation est toujours soustraite, quel que soit son signe publié)
    p = {"creditPaiementSupplementaire": "500", "creditPaiementAnnule": "-200"}
    assert d.ae_cp(p, "creditPaiement") == 300.0
    assert d.ae_cp({"creditPaiementAnnule": "200"}, "creditPaiement") == -200.0


def test_premier_nombre_cellule_multiligne():
    assert d.premier_nombre("1 234 567|dont titre 2 : 12 000") == 1234567.0
    assert d.premier_nombre("titre|-12 500,5") == -12500.5
    assert d.premier_nombre("") == 0.0
    assert d.premier_nombre(None) == 0.0


@pytest.mark.parametrize("entete,contexte,typ,signe", [
    ("Crédits annulés", "", "", -1),
    ("Crédits ouverts", "", "", 1),
    ("Montant", "les crédits suivants sont ouverts", "", 1),
    ("Montant", "ouverts puis annulés", "", -1),
    ("Montant", "", "annulation", -1),
    ("Montant", "", "fonds_de_concours", 1),
    ("Montant", "", "autre", None),
])
def test_signe(entete, contexte, typ, signe):
    assert d._signe(entete, contexte, typ) == signe


def test_montant_compare_reports():
    assert d.montant_compare({}, {"cp": -5.0}, "reports_entrants") == 0.0
    assert d.montant_compare({}, {"cp": 5.0}, "reports_entrants") == 5.0
    assert d.montant_compare({}, {"cp": -5.0}, "annulations") == -5.0
