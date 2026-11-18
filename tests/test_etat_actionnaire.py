"""L'État actionnaire (pipeline/etat_actionnaire.py) : contrat, sommes, confidentialité, neutralité, liens.

Les tests sur site/data/etat_actionnaire tournent sans réseau ni entrepôt ; la reproductibilité et la relecture des
sources demandent l'entrepôt (data/lake/etat_actionnaire) et le cache des entités, sautées sinon. Les tests unitaires
des lecteurs travaillent sur de petits fichiers écrits dans un dossier temporaire.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
DATA = SITE / "etat_actionnaire"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import etat_actionnaire as ea  # noqa: E402
import sirene  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

# Qualificatifs propres au sujet (en plus du lexique partagé) : aucun jugement sur une cession ou un dividende.
JUGEMENTS = re.compile(r"(?<!\w)(?:brad\w*|dilapid\w*|bijoux de famille|rentable\w*|juteu\w*|manne|renflou\w*|sauvetage\w*|"
                       r"gouffre|perte sèche|bonne affaire|mauvaise affaire|vert|rouge|prétendu\w*|artificiel\w*)(?!\w)", re.I)
FICHIERS = ["index.json", "flux.json", "entites.json", "societes_controlees.json"]


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def flux():
    return _lire("flux.json")


@pytest.fixture(scope="module")
def entites():
    return _lire("entites.json")


@pytest.fixture(scope="module")
def index():
    return _lire("index.json")


# --- Fichiers publiés ---------------------------------------------------------------------------------------------------

def test_entete_taille_et_json_compact():
    for nom in FICHIERS:
        brut = (DATA / nom).read_bytes()
        d = json.loads(brut)
        assert d["millesime"] and d["source"] and d["unite"] and len(d["avertissement"]) > 20, nom
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"]), nom
        assert len(brut) < 5_000_000 and b"\n" not in brut, nom


def test_dividendes_trois_lignes_et_total(flux):
    lignes = flux["dividendes"]["lignes"]
    assert [l["code"] for l in lignes] == ["2110", "2116", "2199"]
    for annee in ("2023", "2024", "2025"):
        somme = sum(l["par_annee"][annee]["execution_eur"] for l in lignes)
        assert abs(somme - flux["dividendes"]["total"][annee]["execution_eur"]) < 0.05, annee
    assert flux["dividendes"]["lignes"][0]["par_annee"]["2025"]["plf_eur"] == 1_466_600_000
    assert flux["dividendes"]["lignes"][1]["par_annee"]["2025"]["plf_eur"] == 4_471_576_000
    assert flux["dividendes"]["lignes"][2]["par_annee"]["2025"]["plf_eur"] == 14_782_135


def test_total_seulement_si_toutes_les_lignes_portent_la_mesure(flux):
    for bloc in (flux["dividendes"], flux["compte"]["depenses"]):
        lignes = bloc.get("lignes") or bloc["programmes"]
        for annee, mesures in bloc["total"].items():
            presentes = [l["par_annee"][annee] for l in lignes if annee in l["par_annee"]]
            for m, v in mesures.items():
                assert all(m in p for p in presentes), (annee, m)
                assert abs(sum(p[m] for p in presentes) - v) < 0.05, (annee, m)


def test_serie_longue_des_dividendes(flux):
    s = flux["dividendes"]["serie_longue"]
    assert s["annees"] == list(range(2014, 2026)) and s["unite"] == "milliards d'euros"
    assert len(s["numeraire_md"]) == len(s["actions_md"]) == len(s["total_md"]) == 12
    for n, a, t in zip(s["numeraire_md"], s["actions_md"], s["total_md"]):
        assert abs(n + a - t) < 0.06  # arrondis de la source
    assert s["statuts"] == {"2025": "prévision au 30/08/2025"}
    assert "ne s'y additionne pas" in s["perimetre"]


def test_recettes_du_compte_lignes_et_situation_comptable(flux):
    rec = flux["compte"]["recettes"]
    assert [l["code"] for l in rec["lignes"]] == ["01", "02", "03", "04", "05", "06"]
    assert rec["lignes"][0]["nature"] == "cession" and rec["lignes"][5]["nature"] == "versement_budget_general"
    for annee, solde in flux["compte"]["solde"]["par_annee"].items():
        somme = sum(l["par_annee"][annee]["execution_eur"] for l in rec["lignes"] if annee in l["par_annee"])
        assert abs(somme - solde["recettes_eur"]) <= 1, annee
        assert rec["total"][annee]["execution_eur"] == solde["recettes_eur"]
        hors = somme - rec["lignes"][5]["par_annee"][annee]["execution_eur"]
        assert abs(hors - rec["hors_versement_budget_general"][annee]["execution_eur"]) < 0.05
        # le détail d'exécution d'une ligne redonne son montant
        for l in rec["lignes"]:
            if annee in l["detail_execution"]:
                detail = sum(x["execution_eur"] for x in l["detail_execution"][annee] if x["execution_eur"] is not None)
                assert abs(detail - l["par_annee"][annee]["execution_eur"]) < 0.05, (annee, l["code"])
    assert rec["lignes"][0]["par_annee"]["2026"]["plf_eur"] == 3_225_300_001
    assert rec["total"]["2025"]["lfi_eur"] == 4_415_500_000 and rec["total"]["2026"]["plf_eur"] == 5_421_152_655


def test_solde_du_compte_s_enchaine(flux):
    par = flux["compte"]["solde"]["par_annee"]
    for annee, s in par.items():
        assert abs(s["debut_eur"] + s["recettes_eur"] - s["depenses_eur"] - s["fin_eur"]) <= 2, annee
    assert abs(par["2023"]["fin_eur"] - par["2024"]["debut_eur"]) <= 1 and par["2024"]["fin_eur"] == par["2025"]["debut_eur"]


def test_depenses_programmes_et_actions(flux):
    dep = flux["compte"]["depenses"]
    p731, p732 = dep["programmes"]
    assert (p731["code"], p732["code"]) == ("731", "732")
    for annee, solde in flux["compte"]["solde"]["par_annee"].items():
        somme = p731["par_annee"][annee]["execution_eur"] + p732["par_annee"][annee]["execution_eur"]
        assert abs(somme - solde["depenses_eur"]) <= 1, annee
    actions = {a["code"]: a for a in p731["actions"]}
    assert actions["731-01"]["par_annee"]["2025"] == {"plf_eur": 4_313_500_000, "lfi_eur": 4_313_500_000}
    for annee, mesure in (("2025", "lfi_eur"), ("2026", "plf_eur")):
        somme = sum(a["par_annee"].get(annee, {}).get(mesure, 0) for a in p731["actions"])
        assert abs(somme - p731["par_annee"][annee][mesure]) < 1, (annee, mesure)
    assert p732["actions"][0]["par_annee"]["2025"]["plf_eur"] == 5_153_480_084


def test_ecarts_entre_sources_publies_sans_etre_tranches(flux, index):
    ecarts = flux["ecarts_entre_sources"]
    assert index["ecarts_entre_sources"]["nombre"] == len(ecarts) >= 1
    for e in ecarts:
        a, b = (v["montant_eur"] for v in e["valeurs"][:2])
        assert a != b and e["valeurs"][0]["source"] != e["valeurs"][1]["source"]
        assert "aucun n'est retenu" in e["lecture"]
    for t in flux["rapprochement_senat"]["totaux"]:  # totaux du Sénat : millions arrondis, au million près
        assert abs(t["senat_millions_eur"] * 1e6 - t["autre_source_eur"]) < 1_000_000, t["objet"]


def test_entites_personnes_morales_seulement(entites):
    lignes = entites["dividendes_par_ligne_d_execution"]
    assert [l["code_execution"] for l in lignes] == sorted(l["code_execution"] for l in lignes)
    assert entites["ordre"]["cles"] == ["code_execution"]
    nommees = [l for l in lignes if l["entite"]]
    assert len(nommees) >= 10
    for l in lignes:
        assert l["code_execution"].startswith(l["ligne"])
        if l["entite"]:
            assert sirene.siren_valide(l["entite"]["siren"]) and sirene.personne_morale(l["entite"]["categorie_juridique"])
            assert ea.ENTITES[l["code_execution"]] == l["entite"]["siren"]
        else:  # ligne générique : aucun nom d'entité dans le libellé publié
            assert l["code_execution"] in ea.LIGNES_GENERIQUES, l
    for op in entites["operations_citees"]["operations"]:
        assert sirene.personne_morale(op["entite"]["categorie_juridique"])
        for m in op["mentions"]:
            assert m["montant_eur"] > 0 and m["page"] >= 1 and len(m["citation"]) > 10
            millions = f"{m['montant_eur'] / 1e6:.0f}"
            assert f"{millions} millions" in m["citation"], m


def test_entites_conservation_avec_les_lignes_budgetaires(entites, flux):
    for annee in ("2023", "2024", "2025"):
        somme = sum(l["execution_eur"].get(annee) or 0 for l in entites["dividendes_par_ligne_d_execution"])
        somme += entites["non_verifiees"]["execution_eur"].get(annee, 0)
        assert abs(somme - flux["dividendes"]["total"][annee]["execution_eur"]) <= 1, annee
        for code in ("2110", "2116", "2199"):
            ligne = next(l for l in flux["dividendes"]["lignes"] if l["code"] == code)
            if entites["non_verifiees"]["nombre"] == 0:
                s = sum(l["execution_eur"].get(annee) or 0 for l in entites["dividendes_par_ligne_d_execution"]
                        if l["ligne"] == code)
                assert abs(s - ligne["par_annee"][annee]["execution_eur"]) <= 1, (annee, code)


def test_aucune_personne_physique_ni_elu_nomme():
    """Les documents parlementaires nomment des élus : aucun de ces noms ne passe dans les fichiers publiés."""
    for nom in FICHIERS:
        brut = (DATA / nom).read_text(encoding="utf-8")
        assert not re.search(r"\b(?:M\.|Mme|MM\.|Mmes|rapporteur|sénateur|député)\b", brut), nom
        assert not re.search(r"(?i)pr[eé]nom|courriel|t[eé]l[eé]phone|dirigeant", brut), nom


def test_societes_controlees_insee():
    d = _lire("societes_controlees.json")
    annees = [s["annee"] for s in d["serie"]]
    assert annees == list(range(1995, 2023)) and d["serie"][-1]["societes"] == 1888
    ens = d["activites"][-1]
    assert ens["nom"] == "Ensemble" and ens["societes_2022"] == 1888 and ens["effectifs_2022"] == 571594
    niveau1 = [a for a in d["activites"][:-1] if a["niveau"] == 1]
    assert sum(a["societes_2022"] for a in niveau1) == ens["societes_2022"]
    for a in d["activites"]:  # secret statistique : null avec mention, jamais 0
        for cle in a.get("secret_statistique", []):
            assert a[cle] is None, a
        for cle in ("societes_2021", "societes_2022", "effectifs_2021", "effectifs_2022"):
            assert (a[cle] is None) == (cle in a.get("secret_statistique", [])), (a["nom"], cle)
        if a["niveau"] == 2:
            assert a["parent"] in {x["nom"] for x in niveau1}


def test_liens_avec_recettes_et_arbre(index, flux):
    liens = index["liens"]
    recettes = json.loads((SITE / liens["recettes"]["fichier"]).read_text(encoding="utf-8"))
    assert liens["recettes"]["millesime"] == recettes["millesime"]
    racine = json.loads((SITE / liens["arbre"]["fichier"]).read_text(encoding="utf-8"))
    assert liens["arbre"]["millesime"] == racine["millesime"]

    def chercher(n, ident):
        if n["id"] == ident:
            return n
        return next((r for e in n.get("enfants", []) if (r := chercher(e, ident))), None)

    for noeud in liens["arbre"]["noeuds"]:
        if noeud["present"]:
            n = chercher(racine, noeud["id"])
            assert n and n["md"] == noeud["md"] and n["id"].endswith("/" + noeud["programme"])
            if "2024" in racine["millesime"]:  # même dépense, deux sources : arbre (Md€) et PLRG (euros)
                assert abs(noeud["md"] * 1e9 - noeud["execution_2024_plrg_eur"]) < 1e6, noeud
        else:
            assert noeud["id"] is None and noeud["md"] is None
        bg = next(p for p in flux["budget_general_vers_compte"]["programmes"] if p["code"] == noeud["programme"])
        assert bg["par_annee"]["2024"]["execution_eur"] == noeud["execution_2024_plrg_eur"]
    # aucun programme du compte dans l'arbre du budget général
    for code in ("731", "732"):
        assert ea._noeud_arbre(code) is None
    for f in index["fichiers"]:
        assert (SITE / f["fichier"]).exists()


def test_chiffres_cles_egaux_aux_flux(index, flux):
    c = index["chiffres_cles"]
    a = str(c["annee"])
    rec = flux["compte"]["recettes"]
    assert c["dividendes_eur"] == flux["dividendes"]["total"][a]["execution_eur"]
    assert c["cessions_eur"] == rec["lignes"][0]["par_annee"][a]["execution_eur"]
    assert c["versement_budget_general_eur"] == rec["lignes"][5]["par_annee"][a]["execution_eur"]
    assert c["recettes_compte_eur"] == rec["total"][a]["execution_eur"]
    assert c["depenses_programme_731_eur"] == flux["compte"]["depenses"]["programmes"][0]["par_annee"][a]["execution_eur"]
    assert c["solde_compte_fin_eur"] == flux["compte"]["solde"]["par_annee"][a]["fin_eur"]


def test_sources_et_source_inaccessible(index):
    assert all(s["url"].startswith("https://") and s["licence"] for s in index["sources"])
    hotes = {s["url"].split("/")[2] for s in index["sources"]}
    assert {"data.economie.gouv.fr", "www.insee.fr", "www.senat.fr", "www.assemblee-nationale.fr"} <= hotes
    inacc = index["sources_inaccessibles"]
    assert len(inacc) == 1 and "403" in inacc[0]["motif"] and "non contourné" in inacc[0]["motif"]
    verdicts = {t["verdict"] for t in index["recherche_publique"]["trouvailles"]}
    assert {"réutilisable tel quel", "à adapter", "inspiration seulement"} <= verdicts
    assert all(t["licence"] and t["date"] for t in index["recherche_publique"]["trouvailles"])
    catalogue = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in catalogue["sources"]}
    assert {s["id"] for s in index["sources"]} <= ids


def test_valeur_du_portefeuille_deux_mesures_citees_jamais_additionnees(index):
    v = index["valeur_portefeuille"]
    agence, bilan = v["agence"], v["bilan_etat"]
    assert agence["statut"] == "approché" and bilan["statut"] == "tracé"
    assert "ne s'additionnent pas" in v["definition"]
    serie = agence["serie"]
    assert [p["date"] for p in serie] == sorted(p["date"] for p in serie) and agence["ordre"]["cles"] == ["date"]
    assert [p["valeur_md"] for p in serie] == [128.0, 153.0, 179.5, 209.1]
    for p in serie + [agence["cotees_fin_2025"], bilan]:
        assert p["url"].startswith("https://") and p["annee"] == int(p["date"][:4])
        assert all(c["page"] >= 1 and len(c["texte"]) > 20 for c in p["citations"])
        for cle in ("valeur_md", "valeur_cotee_md", "entreprises", "entreprises_cotees", "entites", "entites_controlees",
                    "entites_non_controlees", "entites_controlees_md", "entites_non_controlees_md"):
            if cle in p:  # chaque montant se lit dans une citation exacte, tel qu'écrit par la source
                assert any(ea._fr(p[cle]) in c["texte"] for c in p["citations"]), (p["date"], cle)
    assert abs(bilan["entites_controlees_md"] + bilan["entites_non_controlees_md"] - bilan["valeur_md"]) < 0.15
    assert bilan["entites_controlees"] + bilan["entites_non_controlees"] == bilan["entites"] == 1508
    # deux périmètres : aucun total ni somme des deux mesures n'est publié
    def cles(x):
        if isinstance(x, dict):
            for k, y in x.items():
                yield k
                yield from cles(y)
        elif isinstance(x, list):
            for y in x:
                yield from cles(y)
    assert not [k for k in cles(v) if "total" in k or "somme" in k or "cumul" in k]
    assert agence["methode_citation"]["texte"].startswith("Précision méthodologique")


def test_bpifrance_et_tsa_rapprochement_justifie(entites):
    lignes = {l["code_execution"]: l for l in entites["dividendes_par_ligne_d_execution"]}
    for code, siren, cj, extrait in (("211609", "483790069", "4120", "« EPIC Bpifrance 100% »"),
                                     ("211668", "542089750", "5710", "« TSA 100% »")):
        l = lignes[code]
        assert l["entite"]["siren"] == siren and l["entite"]["categorie_juridique"] == cj
        assert "Participations directes de l'État" in l["note"] and extrait in l["note"]
    assert ea.PARTICIPATIONS_DIRECTES[2][1:] == ["EPIC Bpifrance 100%", "TSA 100%"]


class _PageFactice:
    """Deux colonnes : la phrase de gauche court sur deux lignes, la colonne de droite s'intercale à la lecture."""

    def __init__(self, mots):
        self.mots = mots

    def extract_words(self, **_):
        return self.mots

    def extract_text(self):
        return " ".join(w["text"] for w in sorted(self.mots, key=lambda w: (round(w["top"]), w["x0"])))


def _mots(x, top, texte):
    out = []
    for m in texte.split():
        out.append({"text": m, "x0": x, "x1": x + 5 * len(m), "top": top})
        x += 5 * len(m) + 2.5
    return out


def test_textes_page_relit_chaque_colonne_d_un_seul_tenant():
    page = _PageFactice(_mots(100, 400, "La valeur totale est") + _mots(320, 400.4, "Le secteur de")
                        + _mots(100, 411, "estimée à 12 Md€.") + _mots(320, 411.3, "l'énergie représente"))
    textes = ea.textes_page(page)
    assert "La valeur totale est estimée à 12 Md€." not in textes[0]  # page entière : colonnes entremêlées
    assert "La valeur totale est estimée à 12 Md€." in textes[1:]
    assert "Le secteur de l'énergie représente" in textes[1:]


def test_neutralite_aucun_qualificatif():
    for nom in FICHIERS:
        d = _lire(nom)
        for cle, t in textes(d):
            assert not fautes(t), (nom, cle, t[:100])
            assert not JUGEMENTS.search(t), (nom, cle, t[:100])
        # tout le fichier, hors citations exactes et titres de sources : aucun des qualificatifs du sujet
        brut = json.dumps({k: v for k, v in d.items() if k != "recherche_publique"}, ensure_ascii=False)
        brut = re.sub(r'"citation":"[^"]*"', "", brut)
        assert not JUGEMENTS.search(brut), nom


# --- Lecteurs (tests unitaires, sans entrepôt) ------------------------------------------------------------------------

def test_nombre_vide_ou_secret_jamais_zero():
    assert ea.nombre("1440725610,17") == 1440725610.17 and ea.nombre("4 313 500 000") == 4_313_500_000
    assert ea.nombre("0") == 0.0 and ea.nombre("-4750920") == -4_750_920
    for vide in ("", None, " ", "s", "nc", "N/A", "-"):
        assert ea.nombre(vide) is None, vide


def test_code_libelle_deux_sens():
    assert ea._code_libelle("2110 - Produits des participations") == ("2110", "Produits des participations")
    assert ea._code_libelle("Versement du budget général - 79106") == ("79106", "Versement du budget général")
    assert ea._code_libelle("211618 - Création 2010 - Entités non contrôlées : X") == \
        ("211618", "Création 2010 - Entités non contrôlées : X")
    assert ea._code_libelle("0") == (None, "0")
    assert ea._programme("Opérations en capital - 731 ") == "731" and ea._programme("Sans code") is None


FORMATS_RECETTES = {
    2023: "Categorie;Section;Ligne_prevision;Ligne_d'execution;LFI;LFR;Total_prevision;Total_recouvrement\n"
          "Recettes non fiscales;21 - D;2110 - Produits financiers;0;100;-10;90;0\n"
          "Recettes non fiscales;21 - D;2110 - Produits financiers;211031 - Entités contrôlées : A;0;0;0;70,5\n"
          "Recettes non fiscales;21 - D;2110 - Produits financiers;211058 - Entités non contrôlées : B;0;0;0;20\n"
          "Recettes fiscales;11 - I;1101 - Impôt;110101 - Créances;0;0;0;999\n",
    2024: "Niveau hiérarchique de la ligne,Catégorie,Section,Ligne de prévision,Ligne d'exécution,LFI,LFR/LFG,"
          "Total des prévisions,Total des recouvrements,Total des recettes**\n"
          "0,Recettes non fiscales,21 - D,2110 - Produits financiers,,100,-10,90,0,0\n"
          "1,Recettes non fiscales,21 - D,2110 - Produits financiers,211031 - Entités contrôlées : A,0,0,0,\"70,5\",0\n"
          "1,Recettes non fiscales,21 - D,2110 - Produits financiers,211058 - Entités non contrôlées : B,0,0,0,20,0\n"
          "2,Recettes non fiscales,21 - D,2110 - Produits financiers (total),2110 - Produits financiers (total),100,-10,90,\"90,5\",0\n",
    2025: "Categorie;Section;Ligne_de_prevision;Ligne_d'execution;Total_des_recouvrements\n"
          "Recettes non fiscales;21 - D;2110 - Produits financiers;211031 - Entités contrôlées : A;70,5\n"
          "Recettes non fiscales;21 - D;2110 - Produits financiers;211058 - Entités non contrôlées : B;20\n",
}


@pytest.mark.parametrize("annee", [2023, 2024, 2025])
def test_lecture_des_trois_formats_de_recettes_du_plrg(annee, tmp_path, monkeypatch):
    (tmp_path / f"plrg_{annee}_recettes.csv").write_text(FORMATS_RECETTES[annee], encoding="utf-8")
    monkeypatch.setattr(ea, "PLRG", tmp_path)
    d = ea.plrg_dividendes(annee)["2110"]
    assert d["mesures"]["execution_eur"] == 90.5
    assert d["execution"] == {"211031": ("Entités contrôlées : A", 70.5), "211058": ("Entités non contrôlées : B", 20.0)}
    if annee != 2025:
        assert d["mesures"]["lfi_plrg_eur"] == 100 and d["mesures"]["lfr_plrg_eur"] == -10
        assert d["mesures"]["prevision_revisee_eur"] == 90
    else:  # le fichier 2025 ne publie pas les prévisions : mesures absentes, jamais 0
        assert set(d["mesures"]) == {"execution_eur"}
    assert ea.plrg_dividendes(annee)["2116"]["mesures"]["execution_eur"] is None


def test_total_publie_different_de_la_somme_arrete_la_production(tmp_path, monkeypatch):
    faux = FORMATS_RECETTES[2024].replace('"90,5"', '"95,5"')
    (tmp_path / "plrg_2024_recettes.csv").write_text(faux, encoding="utf-8")
    monkeypatch.setattr(ea, "PLRG", tmp_path)
    with pytest.raises(AssertionError):
        ea.plrg_dividendes(2024)


def test_recettes_du_compte_ligne_sans_montant_reste_nulle(tmp_path, monkeypatch):
    (tmp_path / "plrg_2024_cs_recouvrements.csv").write_text(
        "Categorie;Compte;Section;Ligne_de_prevision;Ligne_d'execution;Total_des_evaluations;Recouvrements_effectues\n"
        "Compte d'affectation spéciale;Participations financières de l'État;P - 791;Cessions - 79101;0;50;0\n"
        "Compte d'affectation spéciale;Participations financières de l'État;P - 791;Cessions - 79101;Produit - 791101;0;48,5\n"
        "Compte d'affectation spéciale;Participations financières de l’État;P - 791;Autres - 79105;ANRU - 791511;0;\n"
        "Compte d'affectation spéciale;Pensions;P - 741;Retenues - 74101;Retenues - 741101;0;999\n", encoding="utf-8")
    monkeypatch.setattr(ea, "PLRG", tmp_path)
    d = ea.plrg_recettes_compte(2024)
    assert set(d) == {"01", "05"}  # autre compte écarté ; apostrophe typographique reconnue
    assert d["01"]["evaluation_eur"] == 50 and d["01"]["execution_eur"] == 48.5
    assert d["05"]["detail"] == [("791511", "ANRU", None)] and d["05"]["execution_eur"] is None


def test_depenses_avec_ou_sans_colonne_categorie(tmp_path, monkeypatch):
    entete = "Mission;Programme;Titre;LFI;LFR;Report_N-1;Mvts_reglementaires;FDC_et_ADP;Fongibilite_asymetrique;" \
             "Total_CP_Ouverts;Depenses_constatees;Modif_Ouvertures;Modif_Annulations;Report_N+1\n"
    ligne = "Participations financières de l'État;Opérations en capital - 731 ;Autres titres;100;0;20;0;0;0;120;80,25;0;0;40\n"
    autre = "Pensions;Pensions civiles - 741;Titre 2;5;0;0;0;0;0;5;5;0;0;0\n"
    (tmp_path / "plrg_2023_cs_cp.csv").write_text(entete + ligne + autre, encoding="utf-8")
    (tmp_path / "plrg_2024_cs_cp.csv").write_text(
        "Categorie;" + entete + "Comptes d’affectation spéciale;" + ligne + "Comptes d’affectation spéciale;" + autre,
        encoding="utf-8")
    monkeypatch.setattr(ea, "PLRG", tmp_path)
    for annee in (2023, 2024):
        d = ea.plrg_depenses(annee, "cs_cp", ea.PROGRAMMES_COMPTE, True)
        assert d == {"731": {"lfi_plrg_eur": 100, "lfr_plrg_eur": 0, "report_entrant_eur": 20, "credits_ouverts_eur": 120,
                             "execution_eur": 80.25, "report_sortant_eur": 40}}, annee


def test_entite_jamais_nommee_sans_personne_morale_verifiee():
    cache = {"552081317": {"cj": "5599", "nom": "ELECTRICITE DE FRANCE (EDF)", "trouve": True},
             "111111111": {"cj": "1000", "trouve": True},                       # entrepreneur individuel
             "222222222": {"cj": "2110", "nom": "INDIVISION X", "trouve": True},  # groupement de personnes physiques
             "333333333": {"cj": None, "trouve": False},
             "444444444": {"cj": "5710", "trouve": True}}                        # personne morale sans dénomination
    assert ea.entite("552081317", cache) == {"siren": "552081317", "denomination": "ELECTRICITE DE FRANCE (EDF)",
                                             "categorie_juridique": "5599"}
    for s in ("111111111", "222222222", "333333333", "444444444", "999999999", None, "", "12345"):
        assert ea.entite(s, cache) is None, s


def test_total_et_fusion():
    lignes = [{"code": "a", "par_annee": {"2024": {"plf_eur": 1.0, "execution_eur": 2.0}}},
              {"code": "b", "par_annee": {"2024": {"execution_eur": 3.0}, "2025": {"plf_eur": 4.0}}}]
    assert ea._total(lignes) == {"2024": {"execution_eur": 5.0}, "2025": {"plf_eur": 4.0}}
    assert ea._total(lignes, codes={"a"}) == {"2024": {"execution_eur": 2.0, "plf_eur": 1.0}}
    assert ea._par_annee({2025: {"x": None}, 2024: {"x": 1.0, "y": None}}) == {"2024": {"x": 1.0}}
    assert ea._fusion({2024: {"a": 1}}, {2024: {"b": 2}, 2025: {"a": 3}}) == {2024: {"a": 1, "b": 2}, 2025: {"a": 3}}
    assert ea._categorie_source("Création 2010 - Entités non contrôlées : X") == "Entités non contrôlées"
    assert ea._categorie_source("Entités contrôlées") == "Entités contrôlées" and ea._categorie_source("Autres") is None


def test_table_des_entites_coherente():
    assert not set(ea.ENTITES) & ea.LIGNES_GENERIQUES
    assert all(sirene.siren_valide(s) for s in ea.ENTITES.values())
    assert all(c[:4] in ea.LIGNES_DIVIDENDES for c in list(ea.ENTITES) + sorted(ea.LIGNES_GENERIQUES))
    assert all(sirene.siren_valide(s) and mentions for s, mentions in ea.OPERATIONS_SENAT)


# --- Avec l'entrepôt ---------------------------------------------------------------------------------------------------

ENTREPOT = (ea.PLRG / "plrg_2025_recettes.csv").exists() and (ea.DOCS / ea.SENAT["fichier"]).exists() \
    and (ea.DOCS / ea.PAP["fichier"]).exists() and (ea.DOCS / ea.INSEE["fichier"]).exists() and ea.CACHE_ENTITES.exists() \
    and all((d["dossier"] / d["fichier"]).exists() for d in ea.DOCS_VALEUR.values())
avec_entrepot = pytest.mark.skipif(not ENTREPOT, reason="entrepôt data/lake/etat_actionnaire ou cache des entités absent")


@avec_entrepot
def test_production_reproductible_octet_pour_octet(tmp_path):
    empreintes = []
    for graine in ("0", "4242"):
        sortie = tmp_path / graine
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "etat_actionnaire.py"), "produire", "--sortie", str(sortie)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": graine}, timeout=900)
        assert r.returncode == 0, r.stderr[-2000:]
        empreintes.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1] and set(empreintes[0]) == set(FICHIERS)
    publies = {n: hashlib.sha256((DATA / n).read_bytes()).hexdigest() for n in FICHIERS}
    assert empreintes[0] == publies, "site/data/etat_actionnaire n'est pas la sortie de l'entrepôt présent"


@avec_entrepot
def test_citations_du_senat_presentes_dans_le_document_collecte():
    senat = ea.lire_senat()
    for _, mentions in ea.OPERATIONS_SENAT:
        for _, _, citation in mentions:
            assert senat["page_de"](citation) >= 1
    with pytest.raises(SystemExit):
        senat["page_de"]("une phrase qui n'est pas dans le document")


@avec_entrepot
def test_valeur_citation_hors_de_sa_page_arrete_la_production():
    page, citation = ea.VALEUR_AGENCE[2][3][1]
    ea.verifier_citations("jaune_2025", [(page, citation)])
    with pytest.raises(SystemExit):
        ea.verifier_citations("jaune_2025", [(page + 1, citation)])
    with pytest.raises(SystemExit):
        ea.verifier_citations("cge_2025", [(26, "Valeur d'équivalence (EC) | Valeur nette comptable (ENC) 233,0 Md€")])
