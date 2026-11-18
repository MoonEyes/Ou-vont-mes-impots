"""Culture et médias (pipeline/culture_medias.py) : contrat, neutralité, confidentialité, cohérence des sommes.

Les tests sur site/data/culture_medias tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/culture_medias/), sautée sinon.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "culture_medias"
LAKE = ROOT / "data" / "lake" / "culture_medias"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402

import culture_medias as cm  # noqa: E402

FICHIERS = ["index.json", "budget.json", "audiovisuel.json", "presse.json", "cnc.json"]
JUGEMENTS = re.compile(r"(?<!\w)(?:redevance télé|propagande|subventionnite|perfusion|sous perfusion|privilèg\w*|"
                       r"manne|largesses?|trop|insuffisan\w*|excessi\w*)(?!\w)", re.I)
SIGLES_SEULS = re.compile(r"^(?:TSA|TST-E|TST-D|TSV-V|TSV-P|TSV-G|TSV|CNC|FSDP|FSEIP|PLRG|LFI|PLF)$")


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------- unitaires

def test_nombre_jamais_zero_pour_une_absence():
    assert cm.nombre("1 234,5") == 1234.5 and cm.nombre("47451633.32") == 47451633.32 and cm.nombre(0) == 0
    for absent in (None, "", "nc", "ε", "-", True, float("nan")):
        assert cm.nombre(absent) is None
    assert cm.euros("12,6") == 13 and cm.euros("") is None


def test_programme_lu_dans_le_libelle():
    assert cm._programme("Création - 131") == ("Création", 131)
    assert cm._programme("France Télévisions - 841 ") == ("France Télévisions", 841)
    with pytest.raises(cm.DonneeInattendue):
        cm._programme("Sans numéro")


def test_noms_de_personnes_masques():
    publiable = lambda t: None if "ALAIN" in t else t  # noqa: E731 (filtre minimal pour le test)
    assert cm._nom_publie("GROUPE FIGARO", publiable) == ("GROUPE FIGARO", False)
    assert cm._nom_publie("NEXT-NOW (ALAIN WEILL)", publiable, groupe=True) == ("NEXT-NOW", False)
    assert cm._nom_publie("A. WEILL / GROUPE ALTICE", publiable, groupe=True) == (None, True)
    assert cm._nom_publie("ALAIN TITRE", publiable) == (None, True)
    assert cm._nom_publie("  ", publiable) == (None, False)


def test_verification_des_montants_du_pdf():
    lignes = ["Soutiens du CNC : 772,4 M€", "cinéma 315,5 M€ audiovisuel 283,0 M€", "7 2,7 M€", "72,7M€"]
    cm._verifier_montants(lignes, [772.4, 315.5, 283.0, 72.7], 272)
    with pytest.raises(cm.DonneeInattendue):
        cm._verifier_montants(lignes, [772.4, 772.4], 272)       # relevé deux fois, présent une fois
    with pytest.raises(cm.DonneeInattendue):
        cm._verifier_montants(lignes, [1772.4], 272)


def test_actions_et_lignes_hors_action_du_budget_vert():
    def ligne(code_action, code, lib, e24, l25, p26, mission="Culture"):
        return {"type_depense": "Crédits budgétaires", "mission": mission, "numero_programme": "131",
                "programme": "Création", "code_action_si_credit_budgetaire": code_action,
                "action_si_credit_budgetaire": "Action", "code_depense": code, "libelle": lib,
                cm.COLS_BV["execution_2024_eur"]: e24, cm.COLS_BV["lfi_2025_eur"]: l25,
                cm.COLS_BV["plf_2026_eur"]: p26}
    lignes = [ligne("131-01", "131-01-02", "b", "10.4", "1", ""), ligne("131-01", "131-01-01", "a", "10.4", "2", ""),
              ligne("131-02", "131-02", "c", "5", "", "7"), ligne("FDC/ADP", "FDC/ADP", "fonds", "-3", "", ""),
              ligne("131-01", "x", "autre mission", "99", "99", "99", mission="Défense")]
    p = cm.programmes_budget_vert(lignes, ["Culture"])[131]
    a1, a2 = p["actions"]
    assert [li["code_depense"] for li in a1["lignes"]] == ["131-01-01", "131-01-02"]
    assert a1["execution_2024_eur"] == 21 and a1["statut"] == "calculé"     # somme des bruts (20,8), puis arrondi
    assert a1["plf_2026_eur"] is None                                        # absent partout : null, jamais 0
    assert "lignes" not in a2 and a2["lfi_2025_eur"] is None and a2["plf_2026_eur"] == 7
    assert p["somme_actions"]["execution_2024_eur"] == 26                   # hors ligne de retraitement
    assert [h["code"] for h in p["lignes_hors_action"]] == ["FDC/ADP"] and p["lignes_hors_action"][0]["lecture"]


# --------------------------------------------------------------------------------------------- fichiers publiés

@pytest.mark.parametrize("nom", FICHIERS)
def test_entete_et_taille(nom):
    d = _lire(nom)
    assert d["millesime"] and len(d["source"]) >= 20 and d["avertissement"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date_sources"])
    assert (DATA / nom).stat().st_size < 1_000_000


@pytest.mark.parametrize("nom", FICHIERS)
def test_neutralite(nom):
    d = _lire(nom)
    for cle, t in textes(d):
        assert not fautes(t), (nom, cle, fautes(t), t)
        assert not JUGEMENTS.search(t), (nom, cle, t)
    assert "—" not in (DATA / nom).read_text(encoding="utf-8")


def test_index_decrit_les_fichiers_et_les_sources():
    i = _lire("index.json")
    assert sorted(f["fichier"] for f in i["fichiers"]) == sorted(f"culture_medias/{n}" for n in FICHIERS if n != "index.json")
    for f in i["fichiers"]:
        assert f["octets"] == len((DATA.parent / f["fichier"]).read_bytes())
    assert {s["id_catalogue"] for s in i["sources"]} == {s["id_catalogue"] for s in cm.SOURCES.values()}
    catalogue = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    ids = {s["id"]: s for s in catalogue["sources"]}
    for s in i["sources"]:
        assert s["id_catalogue"] in ids and ids[s["id_catalogue"]]["module"] == "pipeline/culture_medias.py"
    assert {t["verdict"] for t in i["recherche_publique"]["trouvailles"]} <= {
        "réutilisable tel quel", "à adapter", "inspiration seulement"}
    assert i["sources_inaccessibles"] and all(s["constat"] for s in i["sources_inaccessibles"])


def test_budget_sommes_coherentes():
    b = _lire("budget.json")
    assert [m["mission"] for m in b["missions"]] == cm.MISSIONS_BUDGET
    nums = [p["programme"] for m in b["missions"] for p in m["programmes"]]
    assert nums == [131, 175, 224, 361, 180, 334]
    for m in b["missions"]:
        for p in m["programmes"]:
            for k in cm.COLS_BV:
                vals = [a[k] for a in p["actions"] if a[k] is not None]
                # somme des actions arrondies : à 1 euro par action près de la somme des bruts
                assert abs(sum(vals) - p["somme_actions"][k]) <= len(vals), (p["programme"], k)
            assert p["plrg_2025"]["depenses_constatees_eur"] > 0
        for k in cm.COLS_BV:
            assert m["somme_programmes"][k] == sum(p["somme_actions"][k] for p in m["programmes"])
    for e in b["ecarts"]:
        assert e["ecart_eur"] == e["montant_eur"] - e["autre_montant_eur"] and e["lecture_ecart"]


def test_depenses_fiscales_null_avec_mention():
    for d in _lire("budget.json")["depenses_fiscales"]["lignes"]:
        vals = [d["chiffrage_2024_eur"], d["chiffrage_2025_eur"], d["chiffrage_2026_eur"]]
        if all(v is None for v in vals):
            assert d["mention_source"], d["code"]
        assert all(v is None or v > 0 for v in vals), d["code"]


def test_audiovisuel_dotations_et_financement():
    a = _lire("audiovisuel.json")
    progs = {s["programme"]: s for s in a["societes"]}
    assert {841, 842, 843, 844, 845, 847} <= set(progs)
    for t in a["totaux"]:
        if t["annee"] <= 2025:
            an = str(t["annee"])
            vals = [s["plrg"][an]["depenses_constatees_eur"] for s in a["societes"] if s["plrg"][an]]
            assert t["depenses_constatees_eur"] == sum(vals) and t["programmes"] == len(vals)
    for r in a["financement"]["recettes"]:
        tva = [li for li in r["lignes"] if "TVA compensatrice" in li["ligne"]]
        assert len(tva) == 1 and tva[0]["recouvrements_eur"] > 3_000_000_000
        assert r["recouvrements_eur"] == sum(li["recouvrements_eur"] for li in r["lignes"])
    assert "TVA" in a["financement"]["mode"] and "tu verses" in a["financement"]["mode"]


def test_presse_personnes_et_sommes():
    p = _lire("presse.json")
    c = p["classement_titres"]
    for t in c["titres"]:
        assert (t["titre"] is None) == t["titre_masque"]
        assert t["groupe"] is None or "(" not in t["groupe"]
        if t["titre"]:
            assert not re.search(r"\b(?:M\.|Mme|Monsieur|Madame)\s", t["titre"])
    assert c["titres_masques"] == sum(t["titre_masque"] for t in c["titres"])
    derniere = next(x for x in c["par_annee"] if x["annee"] == c["derniere_annee"])
    assert derniere["titres"] == len(c["titres"])
    assert derniere["total_aides_eur"] == sum(t["total_aides_eur"] or 0 for t in c["titres"])
    for g in p["groupes"]["lignes"]:
        assert (g["groupe"] is None) == g["groupe_masque"]
        assert g["groupe"] is None or not cm.INITIALE_NOM.search(g["groupe"])
    assert len(p["dispositifs"]["lignes"]) == len(cm.DISPOSITIFS_PRESSE)
    assert [a["code"] for a in p["budget_programme_180"]["actions"]] == ["180-02"]


def test_cnc_sous_totaux():
    c = _lire("cnc.json")
    s = c["soutiens"]
    assert abs(sum(x["total_meur"] for x in s["secteurs"]) - s["total_meur"]) <= cm.TOLERANCE_MEUR
    for x in s["secteurs"]:
        for nat in ("automatiques", "selectifs"):
            assert abs(sum(d["montant_meur"] for d in x[nat]["dispositifs"]) - x[nat]["total_meur"]) <= cm.TOLERANCE_MEUR
    r = c["recettes_fonds_de_soutien"]
    assert abs(r["produit_brut_meur"] - r["prelevement_budget_de_gestion_meur"] - r["total_net_meur"]) <= cm.TOLERANCE_MEUR
    for t in r["taxes"]:
        assert not SIGLES_SEULS.match(t["taxe"]) and len(t["taxe"]) > 10
    assert all(abs(k["ecart_meur"]) <= cm.TOLERANCE_MEUR for k in c["controles"])


# ------------------------------------------------------------------------------------------ reproductibilité

@pytest.mark.skipif(not (LAKE / "culture_medias_budget_vert_plf2026.csv").exists() or
                    not list(LAKE.glob("culture_medias_cnc_bilan_2025.pdf")),
                    reason="entrepôt data/lake/culture_medias absent")
def test_produire_deux_fois_meme_octets(tmp_path):
    empreintes = []
    for i in (1, 2):
        sortie = tmp_path / str(i)
        cm.produire(sortie)
        empreintes.append({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1] and len(empreintes[0]) == 5
