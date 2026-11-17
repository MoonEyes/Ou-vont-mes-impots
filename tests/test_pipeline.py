"""Tests du pipeline sur les donnees deja telechargees (data/raw)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import transform  # noqa: E402

SITE = ROOT / "site" / "data"


@pytest.fixture(scope="module", autouse=True)
def run_transform():
    transform.main()


SANKEYS = ("sankey_etat.json", "sankey_etat_lfi2025.json")
ARBRES_ETAT = {"arbre": "Exécution 2024", "arbre_lfi2025": "LFI 2025"}


def _json(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fichier", SANKEYS)
def test_sankey_conservation_a_chaque_niveau(fichier):
    s = _json(fichier)
    levels = {i: n["level"] for i, n in enumerate(s["nodes"])}
    for lvl in (0, 1, 2):
        sortant = sum(l["value"] for l in s["links"] if levels[l["source"]] == lvl)
        assert sortant == pytest.approx(s["total"], abs=0.05), f"niveau {lvl}"


@pytest.mark.parametrize("fichier", SANKEYS)
def test_chaque_noeud_conserve_son_flux(fichier):
    s = _json(fichier)
    for i, n in enumerate(s["nodes"]):
        if n["level"] in (1, 2):
            entrant = sum(l["value"] for l in s["links"] if l["target"] == i)
            sortant = sum(l["value"] for l in s["links"] if l["source"] == i)
            assert entrant == pytest.approx(sortant, abs=0.01), n["name"]


@pytest.mark.parametrize("fichier,dossier", list(zip(SANKEYS, ARBRES_ETAT)))
def test_sankey_et_arbre_meme_total(fichier, dossier):
    s, a = _json(fichier), _json(f"{dossier}/racine.json")
    assert s["total_net_arbre"] == pytest.approx(a["md"], abs=0.05)
    assert s["millesime"] == a["millesime"]


def test_detail_et_nature_plf2025_retombent_sur_leur_total():
    racine = _json("arbre_plf2025_nature/racine.json")
    n = _json("nature_etat.json")
    assert n["millesime"] == racine["millesime"] == "PLF 2025"
    assert "PLF 2025" in n["libelle"]
    assert sum(t["md"] for t in n["titres"]) == pytest.approx(racine["md"], abs=0.05)
    total_prog = 0.0
    for f in (SITE / "programmes").glob("*.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        assert sum(a["md"] for a in p["actions"]) == pytest.approx(sum(p["nature"].values()), abs=0.01), f.name
        total_prog += sum(p["nature"].values())
    assert total_prog == pytest.approx(racine["md"], abs=0.05)


def _charger_arbre(n):
    if "fichier" in n:
        n = json.loads((SITE / n["fichier"]).read_text(encoding="utf-8"))
    return n


@pytest.mark.parametrize("dossier,profondeur_min", [("arbre", 4), ("arbre_lfi2025", 4), ("arbre_plf2025_nature", 6)])
def test_arbre_chaque_noeud_egal_somme_enfants_jusqu_aux_feuilles(dossier, profondeur_min):
    racine = _json(f"{dossier}/racine.json")
    profondeurs, feuilles = [], []

    def visite(n, d):
        n = _charger_arbre(n)
        enfants = n.get("enfants", [])
        assert n["nom"] != "?", n["id"]
        if enfants:
            assert sum(e["md"] for e in enfants) == pytest.approx(n["md"], abs=1e-4), n["id"]
            for e in enfants:
                visite(e, d + 1)
        else:
            profondeurs.append(d)
            feuilles.append(n["md"])

    visite(racine, 0)
    assert sum(feuilles) == pytest.approx(racine["md"], abs=0.01)
    assert max(profondeurs) >= profondeur_min


def test_arbres_etat_portent_le_bon_millesime():
    """Echoue si le jeu source change d'annees (nouveau budget vert) sans revue humaine."""
    for dossier, millesime in ARBRES_ETAT.items():
        assert _json(f"{dossier}/racine.json")["millesime"] == millesime
        for f in (SITE / dossier).glob("*.json"):
            assert json.loads(f.read_text(encoding="utf-8"))["millesime"] == millesime, f.name
    vert = json.loads((ROOT / "data" / "raw" / "budget_etat_vert.schema.json").read_text(encoding="utf-8"))
    assert {"execution_2024_cp", "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale"} <= set(vert["fields"])


def test_chaque_fichier_du_site_porte_millesime_et_source():
    for f in SITE.rglob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d.get("millesime") and d.get("source"), f.relative_to(SITE)


def _agregat(nom_ligne, texte, annee):
    """Agregat de la situation mensuelle budgetaire (euros) : execution (jeu ODS) ou LFI (piece jointe)."""
    if texte == "Exécution":
        rows = transform.load("situation_budgetaire")
        return next(r[f"31_12_{annee}"] for r in rows if r["ligne_d_information"].strip() == nom_ligne)
    rows = transform.load("situation_budgetaire_lois")
    return transform.num(next(r[annee] for r in rows if r["Ligne d'information"].strip() == nom_ligne
                              and r["Texte législatif"] == texte))


def _branche(dossier, poste):
    racine = _json(f"{dossier}/racine.json")
    noeud = _charger_arbre(next(e for e in racine["enfants"] if e["nom"] == poste))
    return {e["nom"]: e["md"] for e in noeud["enfants"]}


@pytest.mark.parametrize("dossier,texte,annee", [("arbre", "Exécution", "2024"), ("arbre_lfi2025", "LFI", "2025")])
def test_prelevements_sur_recettes_egaux_a_la_situation_budgetaire(dossier, texte, annee):
    psr = _branche(dossier, "Prelevements sur recettes")
    ct = _agregat("PSR au profit des collectivités territoriales", texte, annee) / 1e9
    ue = _agregat("PSR au profit de l'Union européenne", texte, annee) / 1e9
    assert psr == {"Collectivités territoriales": pytest.approx(ct, abs=1e-4),
                   "Union européenne": pytest.approx(ue, abs=1e-4)}


def test_situation_budgetaire_api_et_piece_jointe_concordent():
    for ligne in ("PSR au profit des collectivités territoriales", "Solde budgétaire",
                  "Total dépenses nettes du budget général"):
        assert _agregat(ligne, "Exécution", "2024") == pytest.approx(
            transform.num(next(r["2024"] for r in transform.load("situation_budgetaire_lois")
                               if r["Ligne d'information"].strip() == ligne and r["Texte législatif"] == "Exécution")),
            abs=1)


@pytest.mark.parametrize("cle,texte,annee", [("execution_2024", "Exécution", "2024"), ("lfi_2025", "LFI", "2025")])
def test_charge_de_la_dette_completee_depuis_le_plrg(cle, texte, annee):
    c = _json("meta.json")["controle"]["etat"][cle]["complements_plrg_md"]
    titre4 = _agregat("Charges de la dette de l\u2019Etat", texte, annee) / 1e9
    assert c["117"] + c["355"] == pytest.approx(titre4, abs=0.01)


@pytest.mark.parametrize("cle", ["execution_2024", "lfi_2025"])
def test_rapprochement_plrg_et_conventions_dans_meta(cle):
    e = _json("meta.json")["controle"]["etat"][cle]
    r = e["rapprochement_plrg"]
    assert abs(r["ecart_md"]) / r["plrg_budget_general_hors_rd_md"] < 0.03
    rd = e["remboursements_et_degrevements"]
    assert rd["traitement"] == "retirés par convention"
    assert rd["montant_md"] == pytest.approx(rd["controle_plrg_md"], abs=0.01) and rd["montant_md"] > 100


def test_deficit_deux_comptabilites_sans_melange():
    d = _json("deficit.json")
    etat, apu = d["etat"], d["administrations_publiques"]
    assert "solde_budgetaire" in etat["formule_part_empruntee"] and "B9" in apu["formule_part_empruntee"]
    for nom, a in etat["annees"].items():
        assert a["part_empruntee"] == pytest.approx(
            -a["solde_budgetaire_md"] / (a["depenses_nettes_bg_md"] + a["prelevements_sur_recettes_md"]), abs=1e-3)
        reconstitue = (a["recettes_nettes_bg_md"] + a["fonds_de_concours_md"] - a["depenses_nettes_bg_md"]
                       - a["prelevements_sur_recettes_md"] + a["solde_comptes_speciaux_md"]
                       + a["solde_budgets_annexes_md"])
        assert reconstitue == pytest.approx(a["solde_budgetaire_md"], abs=0.01), nom
    assert {"Exécution 2024", "LFI 2025"} <= set(etat["annees"])
    for annee, a in apu["annees"].items():
        assert 0 < a["part_empruntee"] < 0.2 and a["part_empruntee"] == pytest.approx(-a["B9_md"] / a["TE_md"], abs=1e-3)


def test_arbre_generique_profondeur_libre():
    import arbre
    rows = [{"a": "X", "b": "1", "c": None, "v": 2e9}, {"a": "X", "b": "2", "c": "z", "v": 1e9}]
    niveaux = [{"id": n, "cle": n, "libelle": n} for n in "abc"]
    r = arbre.construire(rows, niveaux, "v")
    x = r["enfants"]["X"]
    assert x["eur"] == 3e9 and x["enfants"]["1"]["enfants"] == {}  # c absent : branche plus courte
    assert x["enfants"]["2"]["enfants"]["z"]["eur"] == 1e9


def test_arbre_administrations_coherent_et_double_compte_explique():
    racine = json.loads((SITE / "arbre_administrations" / "racine.json").read_text(encoding="utf-8"))
    assert {e["nom"] for e in racine["enfants"]} == {"Etat", "Collectivites locales", "Securite sociale"}

    def visite(n):
        if n.get("enfants"):
            assert sum(e["md"] for e in n["enfants"]) == pytest.approx(n["md"], abs=1e-3), n["id"]
            for e in n["enfants"]:
                visite(e)
    visite(racine)
    m = json.loads((SITE / "arbre_administrations" / "methode.json").read_text(encoding="utf-8"))
    surplus = m["somme_administrations_md"] - m["total_consolide_md"]
    # L'ecart de consolidation publie est exactement la difference des deux montants publies (constat I1) ; il est
    # positif et ne depasse pas l'ecart sur les depenses totales, qui couvre tous les transferts entre administrations.
    assert m["ecart_consolidation_md"] == pytest.approx(surplus, abs=0.05)
    assert 0 <= surplus <= m["ecart_depenses_totales_md"]
    assert m["ecart_depenses_totales_md"] >= m["transferts_courants_entre_administrations_md"]
    assert set(m["definitions"]) == {"ecart_consolidation_md", "ecart_depenses_totales_md", "ecart_tables_eurostat_md"}
    # constat M13 : l'ecart entre les deux tables Eurostat est publie, pas seulement tolere
    assert m["ecart_tables_eurostat_md"] == pytest.approx(m["depenses_totales_ensemble_md"] - m["total_consolide_md"], abs=0.05)


def test_recettes_un_impot_va_a_une_seule_administration():
    r = json.loads((SITE / "recettes.json").read_text(encoding="utf-8"))
    for code in ("D211", "D51A_C1", "D61"):
        par = r["impots"][code]["par_administration"]
        for annee, total in par["Ensemble"].items():
            somme = sum(par[a].get(annee, 0) for a in ("Etat", "Collectivites locales", "Securite sociale"))
            assert somme == pytest.approx(total, rel=0.01), (code, annee)


@pytest.mark.parametrize("fichier", SANKEYS)
def test_remboursements_exclus(fichier):
    s = _json(fichier)
    assert not any("Remboursements" in n["name"] for n in s["nodes"])


def _load_avec(nom, lignes_en_plus):
    original = transform.load

    def fake(name):
        rows = original(name)
        return rows + lignes_en_plus if name == nom else rows
    return fake


def test_mission_inconnue_fait_echouer(monkeypatch):
    monkeypatch.setattr(transform, "load", _load_avec("budget_etat_vert", [{
        "mission": "Mission imaginaire", "numero_programme": 999, "programme": "x",
        "execution_2024_cp": 1.0, "lfi_2025_cp_ou_prevision_2025_si_depense_fiscale": 1.0}]))
    with pytest.raises(SystemExit, match="Mission imaginaire"):
        transform.lignes_etat(transform.MILLESIMES[0])


def test_programme_absent_du_budget_vert_non_prevu_fait_echouer(monkeypatch):
    monkeypatch.setattr(transform, "load", _load_avec("plrg_2024_cp", [{
        "Mission": "Justice", "Programme": "Programme fusionne - 998", "Titre": "x", "LFI": "1",
        "Depenses_constatees": "1000"}]))
    with pytest.raises(SystemExit, match="998"):
        transform.lignes_etat(transform.MILLESIMES[0])


def test_codes_insee_et_commune_connue():
    dep44 = _json("communes/44.json")["communes"]
    assert all(len(code) == 5 for code in dep44)
    nom, tfb, _ = dep44["44109"]
    assert nom == "NANTES" and 0 < tfb < 100


def test_jsonstat_extraction():
    data = {
        "id": ["geo", "cat", "time"], "size": [1, 2, 2],
        "dimension": {"cat": {"category": {"index": {"A": 0, "B": 1}}},
                      "time": {"category": {"index": {"2023": 0, "2024": 1}}}},
        "value": {"0": 1, "1": 2, "2": 3},  # B/2024 manquant
    }
    assert transform.jsonstat_series(data, "cat") == {"A": {"2023": 1, "2024": 2}, "B": {"2023": 3}}


def test_derive_de_schema_detectee(tmp_path):
    ref = ROOT / "schemas" / "deficit_france.json"
    original = ref.read_text(encoding="utf-8")
    try:
        ref.write_text(json.dumps({"champ_fantome": "text"}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "check_schema.py")],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 1 and "champ_fantome" in r.stdout
    finally:
        ref.write_text(original, encoding="utf-8")
        (ROOT / "schema_drift.md").unlink(missing_ok=True)
