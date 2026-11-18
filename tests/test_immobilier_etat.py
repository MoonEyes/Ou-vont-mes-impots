"""Immobilier de l'État (pipeline/immobilier_etat.py) : contrat, sommes, confidentialité, neutralité, reproductibilité.

Les tests sur site/data/immobilier_etat tournent sans réseau ni entrepôt ; la relecture des sources et la
reproductibilité demandent l'entrepôt (data/lake/immobilier_etat), sautées sinon. Les lecteurs CSV sont testés sur
de petits fichiers écrits dans un dossier temporaire.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data" / "immobilier_etat"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import immobilier_etat as ie  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

FICHIERS = ["index.json", "parc.json", "loyers.json", "cessions.json", "compte.json"]
# Qualificatifs propres au sujet (en plus du lexique partagé) : aucun jugement sur une vente, un loyer ou un bien.
JUGEMENTS = re.compile(r"(?<!\w)(?:brad\w*|bradage|dilapid\w*|bijoux de famille|bonne affaire|mauvaise affaire|"
                       r"rentable\w*|juteu\w*|manne|abusi\w*|excessi\w*|vétuste\w*|prétendu\w*|ruineu\w*)(?!\w)", re.I)
LAKE_OK = (ie.DOCS / ie.DPT["fichier"]).exists() and (ie.LAKE / "immobilier_etat_parc_2021.csv").exists()


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def docs():
    return {n: _lire(n) for n in FICHIERS}


def test_entete_taille_et_json_compact():
    for nom in FICHIERS:
        brut = (DATA / nom).read_bytes()
        d = json.loads(brut)
        assert d["millesime"] and d["source"] and d["unite"] and len(d["avertissement"]) > 20, nom
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"]), nom
        assert len(brut) < 1_000_000 and b"\n" not in brut, nom


def test_inventaire_quatre_perimetres(docs):
    per = {p["id"]: p for p in docs["parc.json"]["inventaire"]["perimetres"]}
    assert set(per) == {"global", "occupes_etat_et_operateurs", "occupes_etat", "comptable"}
    g = per["global"]
    assert g["annees"] == [2019, 2020, 2021, 2022, 2023, 2024]
    assert g["total_nombre"][-1] == 226915 and g["batiments_nombre"][-1] == 195745
    assert g["batiments_surface_millions_m2"][-1] == 96.7
    for p in per.values():
        assert len(p["batiments_nombre"]) == len(p["terrains_nombre"]) == len(p["total_nombre"]) == 6


def test_valeur_et_vnc_par_ministere(docs):
    v = docs["parc.json"]["valeur"]
    assert v["controlee"]["annees"][-1] == 2024 and v["controlee"]["millions_eur"][-1] == 74895
    pm = v["par_ministere"]
    assert len(pm["ministeres"]) == 14 and pm["total_millions_eur"][-1] == 73630
    # les cases vides du document (biens remis au Domaine avant 2023) restent null, jamais 0
    domaine = next(m for m in pm["ministeres"] if m["ministere"] == "Biens remis au Domaine")
    assert domaine["millions_eur"][:6] == [None] * 6 and domaine["millions_eur"][6:] == [788, 864]
    for j, tot in enumerate(pm["total_millions_eur"]):
        s = sum(m["millions_eur"][j] or 0 for m in pm["ministeres"])
        assert abs(s - tot) <= 2, (j, s, tot)


def test_loyers_et_grandes_prises_a_bail(docs):
    l = docs["loyers.json"]
    assert l["loyers_payes"]["annees"][0] == 2014 and l["loyers_payes"]["millions_eur"][-1] == 1950
    dep = l["depenses_immobilieres"]
    loyers_dep = next(n for n in dep["natures"] if n["nature"] == "Loyers")["millions_eur"]
    assert loyers_dep == l["loyers_payes"]["millions_eur"][4:]  # 2018-2024 : même série dans les deux tableaux
    baux = l["grandes_prises_a_bail"]["baux"]
    assert len(baux) == 29
    for b in baux:
        assert abs(b["loyer_annuel_ht_eur"] / b["surface_m2"] - b["prix_m2_eur"]) < 0.02, b
        assert "bailleur" not in b and b["occupant"] and b["ministere"]
    assert baux[2]["occupant"].startswith("Autorité de régulation de la communication audiovisuelle")


def test_cessions_mesures_distinctes(docs):
    c = docs["cessions.json"]
    lignes = {l["annee"]: l for l in c["comparaison_par_annee"]["lignes"]}
    assert lignes[2024]["prix_actes_millions_eur"] == 222 and lignes[2024]["encaissements_millions_eur"] == 199
    assert lignes[2013]["prix_actes_millions_eur"] is None  # non publié : null, jamais 0
    g = c["plus_de_2_millions_2024"]
    assert abs(sum(x["prix_eur"] for x in g["cessions"]) - g["total_eur"]) <= 1
    assert len(g["cessions"]) == 16 and g["cessions"][6]["commune"] == "Lyon 7e Arrondissement"
    pn = c["par_nature"]
    assert pn["total_nombre"] == [661, 645, 549]
    adm = c["par_administration_occupante"]
    spm = next(a for a in adm["administrations"] if a["administration"] == "Services du Premier ministre")
    assert spm["eur"][6] is None  # cellule vide du document


def test_compte_somme_recettes_et_depenses(docs):
    c = docs["compte.json"]
    for a, s in c["solde"]["par_annee"].items():
        rec = sum(l["par_annee"][a]["execution_eur"] for l in c["recettes"]["lignes"] if a in l["par_annee"])
        assert abs(rec - s["recettes_eur"]) <= 1, a
        dep = sum(p["par_annee"].get(a, {}).get("execution_eur", 0) for p in c["depenses"]["programmes"])
        assert abs(dep - s["depenses_eur"]) <= 1, a
        assert abs(s["debut_eur"] + s["recettes_eur"] - s["depenses_eur"] - s["fin_eur"]) <= 1, a
    for l in c["recettes"]["lignes"]:
        for a, det in l["detail_execution"].items():
            assert abs(sum(d["execution_eur"] or 0 for d in det) - l["par_annee"][a]["execution_eur"]) <= 1
    prev = c["prevision"]
    assert prev["total_recettes"]["lfi_2025_eur"] == 340_000_000
    assert sum(a["cp_plf_2026_eur"] for a in prev["actions_723"]) == prev["total_723"]["cp_plf_2026_eur"] == 321_500_000


def test_jeu_ouvert_agrege_sans_colonne_nominative(docs):
    j = docs["parc.json"]["jeu_ouvert"]["jeux"]["2021"]
    assert sum(m["biens"] for m in j["par_ministere"]) == j["biens"]
    assert sum(d["biens"] for d in j["par_departement"]) == j["biens_france"]
    texte = json.dumps(docs, ensure_ascii=False)
    for interdit in ('"adresse"', '"latitude"', '"longitude"', '"libelle_proprietaire"', '"designation_site"',
                     '"code_chorus"', '"bailleur"', '"acquereur"'):
        assert interdit not in texte, interdit
    # propriétaires et acquéreurs : catégories seulement
    cats = {c["categorie"] for c in j["par_type_proprietaire"]}
    assert "Personne Physique" in cats and all(len(c) < 60 for c in cats)


def test_colonnes_lues_sans_donnee_nominative():
    assert not set(ie.COLONNES_PARC) & ie.COLONNES_INTERDITES
    assert not set(ie.COLONNES_CESSIONS) & ie.COLONNES_INTERDITES
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    for s in cat["sources"]:
        if s.get("domaine") == "immobilier_etat" and s["type"] == "ods_export":
            assert s.get("select"), s["id"]
            assert not set(s["select"].split(",")) & ie.COLONNES_INTERDITES, s["id"]


def test_ecarts_publies_sans_etre_tranches(docs):
    ix = docs["index.json"]
    assert ix["ecarts_entre_sources"]
    for e in ix["ecarts_entre_sources"]:
        assert len(e["valeurs"]) >= 2 and "aucun n'est retenu" in e["lecture"]
    assert ix["recherche_publique"]["trouvailles"]
    for f in ix["fichiers"]:
        assert (ROOT / "site" / "data" / f["fichier"]).exists()


def test_neutralite(docs):
    fautes_trouvees = []
    for nom, d in docs.items():
        for cle, t in textes(d):
            fautes_trouvees += [f"{nom} {cle} : {f}" for f in fautes(t)]
            if JUGEMENTS.search(t):
                fautes_trouvees.append(f"{nom} {cle} : {t[:60]}")
        assert "—" not in json.dumps(d, ensure_ascii=False), nom
    assert not fautes_trouvees, fautes_trouvees[:5]


# --- Lecteurs (fichiers temporaires) ----------------------------------------------------------------------------------

def test_nombre_jamais_zero_pour_absent():
    assert ie.nombre("") is None and ie.nombre("nc") is None and ie.nombre("-") is None
    assert ie.nombre("1 579") == 1579 and ie.nombre("94 313 511*") == 94313511 and ie.nombre("73 000 ha") == 73000
    assert ie.nombre("13 193 000,00 €") == 13193000 and ie.nombre("0.2") == 0.2


def test_lecture_plrg(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, "PLRG", tmp_path)
    (tmp_path / "plrg_2024_cs_recouvrements.csv").write_text(
        "Categorie;Compte;Section;Ligne_de_prevision;Ligne_d'execution;Total_des_evaluations;Recouvrements_effectues\n"
        f"CAS;{ie.COMPTE};x - 761;Produits des cessions immobilières - 76101;0;179800000;0\n"
        f"CAS;{ie.COMPTE};x - 761;Produits des cessions immobilières - 76101;Cessions A - 761601;0;10,5\n"
        f"CAS;{ie.COMPTE};x - 761;Produits des cessions immobilières - 76101;Cessions B - 761602;0;\n"
        "CAS;Autre compte;x - 791;Autre - 79101;Y - 791011;0;5\n", encoding="utf-8")
    r = ie.plrg_recettes(2024)
    assert list(r) == ["76101"] and r["76101"]["evaluation_eur"] == 179800000
    assert r["76101"]["execution_eur"] == 10.5 and r["76101"]["detail"][1][2] is None


def test_agregat_parc():
    lignes = [{"type": "Bureau", "surface_m2": "100", "ministere": "A"},
              {"type": "Espace naturel", "surface_m2": "99999", "ministere": "A"},
              {"type": "Logement", "surface_m2": "", "ministere": "B"}]
    a = {x["cle"]: x for x in ie._agreger(lignes, lambda l: l["ministere"])}
    assert a["A"]["batiments_surface_m2"] == 100 and a["A"]["emprises"] == 1
    assert a["B"]["batiments_surface_non_renseignee"] == 1 and a["B"]["batiments_surface_m2"] == 0


# --- Relecture des sources et reproductibilité (entrepôt requis) ------------------------------------------------------

@pytest.mark.skipif(not LAKE_OK, reason="entrepôt data/lake/immobilier_etat absent")
def test_production_reproductible(tmp_path):
    ie.produire(tmp_path)
    for nom in FICHIERS:
        assert hashlib.sha256((tmp_path / nom).read_bytes()).hexdigest() == \
            hashlib.sha256((DATA / nom).read_bytes()).hexdigest(), nom
