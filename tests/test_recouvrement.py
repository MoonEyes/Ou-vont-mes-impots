"""Contrôle et recouvrement (pipeline/recouvrement.py) : séparation des notions, neutralité, cohérence, lecture des
tableaux.

Les tests sur site/data/recouvrement tournent sans réseau ni entrepôt ; la relecture des sources, la vérification des
citations et la reproductibilité demandent l'entrepôt (data/lake/recouvrement/), sautées sinon.
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
DATA = ROOT / "site" / "data" / "recouvrement"
LAKE = ROOT / "data" / "lake" / "recouvrement"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "pipeline"))
from test_neutralite import fautes, textes  # noqa: E402
import recouvrement as rec  # noqa: E402

FICHIERS = ["index.json", "controle_fiscal.json", "controle_urssaf.json", "impayes.json", "apurements_etat.json",
            "estimations.json"]
NOTIONS = {"notifie", "encaisse", "estimation", "restitution", "apurement", "taux_impayes", "activite"}
# Jugements propres au sujet, en plus du lexique partagé : aucun mot qui désigne un coupable ou un camp.
JUGEMENTS = re.compile(r"(?<!\w)(?:fraudeurs?|tricheu\w*|voleu\w*|laxis\w*|impuni\w*|chasse\w*|traque\w*|manne|"
                       r"cagnotte|pas assez|insuffisan\w*|excessi\w*|record\w*|mauvais payeurs?|malhonn\w*|"
                       r"pire\w*|meilleur\w*|contre les (?:riches|pauvres|patrons|chômeurs|assistés))(?!\w)", re.I)
# Clés rédigées par le pipeline en plus de celles de tests/test_neutralite.py (libellés, titres, objets, repères).
CLES_AXE = {"libelle", "titre", "objet", "texte", "contenu", "repere", "confidentialite", "regles", "conclusion",
            "champ", "lecture_ecart", "restitution_note", "encaisse_note", "estimation_note", "precision",
            "annee_donnees_note"}
entrepot = pytest.mark.skipif(not (LAKE / "recouvrement_documents").exists(),
                              reason="entrepôt data/lake/recouvrement absent")


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return _lire("index.json")


@pytest.fixture(scope="module")
def fiscal():
    return _lire("controle_fiscal.json")


@pytest.fixture(scope="module")
def urssaf():
    return _lire("controle_urssaf.json")


@pytest.fixture(scope="module")
def estimations():
    return _lire("estimations.json")


def _serie(doc: dict, sid: str) -> dict:
    return next(s for s in doc["series"] if s["id"] == sid)


def _parcourir(x, chemin=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield f"{chemin}/{k}", k, v
            yield from _parcourir(v, f"{chemin}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _parcourir(v, f"{chemin}/{i}")


# ------------------------------------------------------------------------------------------------------------
# Forme générale
# ------------------------------------------------------------------------------------------------------------

def test_fichiers_presents_avec_entete_et_taille():
    for nom in FICHIERS:
        f = DATA / nom
        assert f.exists(), nom
        assert f.stat().st_size < 5_000_000, nom
        d = json.loads(f.read_text(encoding="utf-8"))
        for cle in ("millesime", "source", "unite", "avertissement", "collecte_le"):
            assert d.get(cle), (nom, cle)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"])
    assert sorted(p.name for p in DATA.glob("*.json")) == sorted(FICHIERS)


def test_liens_fichiers_de_l_index(index):
    for f in index["fichiers"]:
        assert (ROOT / "site" / "data" / f["fichier"]).exists(), f["fichier"]
    for vue in index["vues"]:
        for notion in ("notifie", "encaisse", "restitution", "estimation"):
            for m in vue[notion]:
                assert (ROOT / "site" / "data" / m["fichier"]).exists()


def test_chaque_source_a_url_licence_et_document(index):
    ids = {s["id"] for s in index["sources"]}
    assert ids == set(rec.SOURCES)
    for s in index["sources"]:
        assert s["url"].startswith("https://") and s["licence"] and s["producteur"]
    officiels = ("urssaf.fr", "economie.gouv.fr", "data.gouv.fr", "assemblee-nationale.fr", "strategie-plan.gouv.fr",
                 "ccomptes.fr", "ec.europa.eu")
    for s in index["sources"]:
        hote = s["url"].split("/")[2]
        assert hote.endswith(officiels), hote


# ------------------------------------------------------------------------------------------------------------
# Les trois notions restent séparées
# ------------------------------------------------------------------------------------------------------------

def test_notions_definies_et_utilisees(index, fiscal, estimations):
    assert {"notifie", "encaisse", "estimation", "restitution", "apurement"} <= set(index["notions"])
    for n in index["notions"].values():
        assert len(n["definition"]) > 60
    assert {s["notion"] for s in fiscal["series"]} == {"notifie", "encaisse", "activite"}
    assert all(e["notion"] == "estimation" for e in estimations["estimations"])
    for nom in FICHIERS:
        for chemin, cle, v in _parcourir(_lire(nom)):
            if cle == "notion":
                assert v in NOTIONS, (nom, chemin, v)


def test_une_serie_ne_melange_pas_notifie_et_encaisse(fiscal):
    for s in fiscal["series"]:
        encaisse = s["serie"].startswith("encaissements")
        assert (s["notion"] == "encaisse") == encaisse, s["id"]
        assert (s["groupe"] == "encaissements") == encaisse, s["id"]
        assert s["unite"] == ("nombre" if s["notion"] == "activite" else "M€"), s["id"]
        assert len(s["annees"]) == len(s["valeurs"]), s["id"]


def test_chaque_estimation_a_producteur_perimetre_methode_annee(estimations):
    assert len(estimations["estimations"]) >= 6
    for e in estimations["estimations"]:
        for cle in ("producteur", "perimetre", "methode", "publication", "citation"):
            assert len(e[cle]) >= 10, (e["id"], cle)
        assert e["annee_publication"] >= 2024
        assert e["annee_donnees"] is not None or e.get("annee_donnees_note"), e["id"]
        assert e["valeur"] is not None or (e["valeur_basse"] is not None and e["valeur_haute"] is not None), e["id"]
        if e["valeur_basse"] is not None:
            assert e["valeur_basse"] < e["valeur_haute"], e["id"]
        assert e["source"]["document"].startswith("data/lake/recouvrement/")


def test_chaque_fichier_de_montants_a_producteur_perimetre_methode():
    for nom in ("controle_fiscal.json", "controle_urssaf.json", "impayes.json", "apurements_etat.json"):
        d = _lire(nom)
        assert len(d["producteur"]) >= 3, nom
        for cle in ("perimetre", "methode"):
            assert len(d[cle]) >= 60, (nom, cle)
        assert d["sphere"] in ("fiscale", "sociale")


def test_vues_de_l_index_separent_les_notions(index):
    assert [(v["sphere"], v["id"]) for v in index["vues"]] == sorted((v["sphere"], v["id"]) for v in index["vues"])
    for vue in index["vues"]:
        for notion in ("encaisse", "restitution", "estimation"):
            assert vue[notion] or vue.get(f"{notion}_note"), (vue["id"], notion)
        assert vue["notifie"], vue["id"]
        # une estimation n'est jamais rangée parmi les montants notifiés ou encaissés
        for notion in ("notifie", "encaisse", "restitution"):
            for m in vue[notion]:
                if m["fichier"].endswith("estimations.json"):
                    assert m["id"].startswith("hcfips_detecte") or m["id"].startswith("hcfips_recouvre"), m
        for m in vue["estimation"]:
            assert m["fichier"] == "recouvrement/estimations.json"


# ------------------------------------------------------------------------------------------------------------
# Sphère fiscale et sphère sociale : ni opposées ni additionnées
# ------------------------------------------------------------------------------------------------------------

def test_aucun_total_entre_spheres_ni_entre_estimations(index, estimations):
    interdits = re.compile(r"total_(?:fraude|general|estim|fiscal_et|spheres)|fraude_totale|somme_estim|"
                           r"fiscal_plus_social|ecart_fiscal_social|rapport_fiscal_social|ratio", re.I)
    for nom in FICHIERS:
        for chemin, cle, _ in _parcourir(_lire(nom)):
            assert not interdits.search(cle), (nom, chemin)
    assert estimations["estimation_ensemble_fraude_fiscale"]["valeur"] is None
    assert "total" not in estimations and "somme" not in estimations
    # chaque objet porte une seule sphère ; aucun objet ne réunit des montants des deux
    for vue in index["vues"]:
        assert vue["sphere"] in ("fiscale", "sociale")
    par_fichier = {"controle_fiscal.json": "fiscale", "apurements_etat.json": "fiscale",
                   "controle_urssaf.json": "sociale", "impayes.json": "sociale"}
    for nom, sphere in par_fichier.items():
        assert _lire(nom)["sphere"] == sphere


def test_regles_de_lecture_ecrites(index, estimations):
    regles = " ".join(index["regles"])
    assert "ni additionnées ni rapportées" in regles
    assert "ne sont jamais additionnées" in regles
    assert "restitutions" in regles.lower()
    assert "Aucune somme d'estimations" in estimations["regle"]
    assert estimations["ordre"]["cles"] == ["sphere", "annee_publication", "id"]
    cles = [(e["sphere"], e["annee_publication"], e["id"]) for e in estimations["estimations"]]
    assert cles == sorted(cles)


def test_aucune_comparaison_fiscal_social_dans_les_textes():
    oppose = re.compile(r"(?:fraude|contrôle) fiscal\w* (?:est|sont|représente\w*|dépasse\w*) [^.]{0,60}"
                        r"(?:fois|plus|moins|supérieur\w*|inférieur\w*) [^.]{0,60}soci\w+|"
                        r"soci\w+ (?:est|sont|représente\w*|dépasse\w*) [^.]{0,60}(?:fois|plus|moins|supérieur\w*|"
                        r"inférieur\w*) [^.]{0,60}fiscal\w*", re.I)
    for nom in FICHIERS:
        for chemin, cle, v in _parcourir(_lire(nom)):
            if isinstance(v, str) and cle != "citation":
                assert not oppose.search(v), (nom, chemin, v[:120])


def test_absence_d_estimation_d_ensemble_citee_telle_quelle(estimations):
    c = {x["id"]: x for x in estimations["constats"]}
    assert c["cour_absence_estimation"]["citation"] == (
        "L’absence d’estimation statistique de l’écart fiscal et de la fraude fiscale constitue une carence "
        "regrettable que la Cour a signalée à plusieurs reprises.")
    assert c["cour_absence_estimation"]["producteur"] == "Cour des comptes"
    assert "ccomptes.fr" in c["cour_absence_estimation"]["source"]["url"]
    assert "30 ou de 130 Md€" in c["cour_ordre_de_grandeur"]["citation"]
    assert "ne doivent pas être ajoutés" in c["hcfips_non_addition"]["citation"]
    assert set(estimations["estimation_ensemble_fraude_fiscale"]["constats"]) <= set(c)
    # aucun des deux chiffres que la Cour refuse de départager n'est publié comme valeur
    for e in estimations["estimations"]:
        if e["sphere"] == "fiscale" and e["unite"] == "Md€":
            assert (e["valeur"] or e["valeur_haute"]) < 30, e["id"]


# ------------------------------------------------------------------------------------------------------------
# Restitutions à côté des redressements
# ------------------------------------------------------------------------------------------------------------

def test_restitutions_publiees_a_cote_des_redressements(urssaf, index):
    t = urssaf["controle"]["total"]
    n = len(urssaf["annees"])
    assert len(t["redressements_eur"]) == len(t["restitutions_eur"]) == len(t["regularisations_eur"]) == n
    assert all(v is not None and v > 0 for v in t["restitutions_eur"])
    for typ in urssaf["controle"]["types"]:
        assert set(typ) >= {"redressements_eur", "restitutions_eur"}
        for r, s in zip(typ["redressements_eur"], typ["restitutions_eur"]):
            assert (r is None) == (s is None), typ["type_action"]
    for o in urssaf["organismes"]:
        if o["controle"]:
            assert len(o["controle"]["restitutions_eur"]) == len(o["controle"]["redressements_eur"]) == n
    vue = next(v for v in index["vues"] if v["id"] == "controle_urssaf")
    assert vue["restitution"] and vue["restitution"][0]["valeur"] == t["restitutions_eur"][-1]
    assert vue["notifie"][0]["valeur"] == t["redressements_eur"][-1]


def test_identite_regularisations_et_sommes_urssaf(urssaf):
    t = urssaf["controle"]["total"]
    for g, r, s in zip(t["regularisations_eur"], t["redressements_eur"], t["restitutions_eur"]):
        assert abs(g - (r + s)) <= 2
    assert urssaf["controle"]["identite_regularisations"]["ecart_max_eur"] <= 2
    for bloc, cle in (("controle", "redressements_eur"), ("controle", "restitutions_eur"),
                      ("travail_dissimule", "redressements_eur")):
        for i in range(len(urssaf["annees"])):
            par_type = sum(x[cle][i] or 0 for x in urssaf[bloc]["types"])
            par_org = sum((o[bloc][cle][i] or 0) for o in urssaf["organismes"] if o[bloc])
            assert abs(par_type - urssaf[bloc]["total"][cle][i]) <= 2, (bloc, cle, i)
            assert abs(par_org - urssaf[bloc]["total"][cle][i]) <= len(urssaf["organismes"]), (bloc, cle, i)


def test_organismes_par_ordre_alphabetique_sans_personne(urssaf):
    noms = [o["nom_tri"] for o in urssaf["organismes"]]
    assert noms == sorted(noms) and urssaf["ordre"]["cles"] == ["nom_tri"]
    assert all(re.match(r"^(Urssaf|CGSS|CSS) ", o["organisme"]) for o in urssaf["organismes"])


def test_absent_reste_null_jamais_zero(urssaf):
    prevention = next(t for t in urssaf["controle"]["types"] if t["type_action"] == "Prévention")
    assert all(v is None for v in prevention["redressements_eur"])
    assert all(v is not None for v in prevention["nombre_actions"])


# ------------------------------------------------------------------------------------------------------------
# Contrôle fiscal : séries, écarts entre sources, cohérence
# ------------------------------------------------------------------------------------------------------------

def test_series_fiscales_couvrent_1996_a_2024(fiscal):
    a = _serie(fiscal, "annuaire_total_droits")
    assert a["annees"] == list(range(1996, 2020)) and all(v is not None for v in a["valeurs"])
    d = _serie(fiscal, "dpt_total_droits_penalites")
    assert d["annees"] == list(range(2016, 2025)) and all(v is not None for v in d["valeurs"])
    assert _serie(fiscal, "dpt_encaissements_total")["annees"] == list(range(2016, 2025))


def test_valeurs_relues_dans_les_tableaux_publies(fiscal):
    def v(sid, annee):
        s = _serie(fiscal, sid)
        return s["valeurs"][s["annees"].index(annee)]
    assert v("annuaire_total_droits", 1996) == 10249.6
    assert v("annuaire_total_droits", 2010) == 13113 and v("annuaire_total_droits", 2019) == 11450.13
    assert v("annuaire_place_penalites", 2019) == 1758.41
    assert v("dpt_total_droits_penalites", 2024) == 16673 and v("dpt_total_droits_penalites", 2016) == 17721
    assert v("dpt_place_penalites", 2020) == 961            # ligne où deux lectures des milliers sont possibles
    assert v("dpt_pieces_enr", 2020) == 1351                # nombre imprimé sans espace des milliers
    assert v("dpt_credits_non_rembourses", 2024) == 3380
    assert v("dpt_encaissements_total", 2024) == 11442 and v("dpt_encaissements_stdr", 2016) == 2476
    assert v("dpt_encaissements_stdr", 2024) == 0           # 0 publié par la source, pas une absence


def test_coherence_arithmetique_des_tableaux(fiscal):
    c = fiscal["coherence"]
    for cle in ("dpt_total_droits_egale_place_plus_pieces", "dpt_droits_et_penalites_egale_droits_plus_penalites",
                "dpt_encaissements_total_egale_hors_stdr_plus_stdr", "annuaire_total_droits_egale_place_plus_pieces"):
        assert c[cle] <= 3, (cle, c[cle])
    assert all(x["ecart"] == 0 for x in fiscal["raccord_editions_2010"]["series"])
    assert len(fiscal["raccord_editions_2010"]["series"]) >= 20


def test_ecarts_entre_sources_publies_non_tranches(fiscal):
    e = [x for x in fiscal["ecarts_entre_sources"] if x["serie"] == "total_droits"]
    assert [x["annee"] for x in e] == [2016, 2017, 2018, 2019]
    for x in e:
        assert x["source"] == "annuaires" and x["autre_source"] == "dpt_2026"
        assert abs(x["ecart"] - (x["autre_valeur"] - x["valeur"])) < 0.01
        # l'écart est celui des crédits d'impôt non remboursés, présentés à part dans le document de 2026
        assert abs(abs(x["ecart"]) - x["credits_non_rembourses_dpt"]) <= 2, x
    assert "ne sont pas raccordées" in fiscal["lecture_ecart"]
    # les deux séries restent publiées, aucune n'est retirée
    assert _serie(fiscal, "annuaire_total_droits") and _serie(fiscal, "dpt_total_droits")


def test_plaintes_totaux(fiscal):
    p = fiscal["plaintes"]
    for i in range(len(p["annees"])):
        assert sum(r["valeurs"][i] for r in p["par_procede"]) == p["total"][i]
        assert sum(r["valeurs"][i] for r in p["par_secteur"]) == p["total"][i]


def test_taux_de_recouvrement_repris_tel_quel(fiscal):
    t = fiscal["taux_recouvrement"]
    assert t["taux_net_pct"] == 67.99 and t["taux_brut_pct"] == 51.6
    assert "67,99 %" in t["citation"] and "51,60 %" in t["citation"]
    # aucun taux encaissé / notifié n'est calculé par le pipeline
    for chemin, cle, _ in _parcourir(fiscal):
        assert not re.search(r"taux_encaisse|encaisse_sur_notifie|part_encaissee", cle), chemin


# ------------------------------------------------------------------------------------------------------------
# Taux d'impayés et comptes de l'État
# ------------------------------------------------------------------------------------------------------------

def test_taux_d_impayes():
    d = _lire("impayes.json")
    n = d["national"]
    assert n["mois"][0] == "2004-01" and n["mois"] == sorted(n["mois"]) and len(set(n["mois"])) == len(n["mois"])
    for cle in ("fin_mois", "fin_mois_suivant", "a_90_jours"):
        assert len(n[cle]) == len(n["mois"])
        assert all(v is None or 0 <= v <= 100 for v in n[cle])
    assert n["a_90_jours"][-1] is None and n["fin_mois"][-1] is not None   # recul de trois mois : null, pas 0
    assert [r["nom_tri"] for r in d["regions"]] == sorted(r["nom_tri"] for r in d["regions"])
    for r in d["regions"]:
        assert len(r["mois"]) == len(r["fin_mois"]) == len(r["a_90_jours"])


def test_apurements_etat():
    d = _lire("apurements_etat.json")
    assert d["annees"] == list(range(d["annees"][0], d["annees"][-1] + 1)) and len(d["annees"]) >= 9
    assert {c["categorie"] for c in d["comptes"]} == {"admission_en_non_valeur", "decision_gracieuse"}
    for c in d["comptes"]:
        assert len(c["montants_eur"]) == len(d["annees"]) and all(v is None or v >= 0 for v in c["montants_eur"])
        assert c["libelle_source"]
    assert not any("total" in k for c in d["comptes"] for k in c)
    assert "pas seulement" in d["avertissement"]


# ------------------------------------------------------------------------------------------------------------
# Neutralité et confidentialité
# ------------------------------------------------------------------------------------------------------------

def _textes_axe(x, cle=None, dans=False):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("citation", "notes_sources", "libelle_source", "definitions") and not dans:
                continue  # textes repris de la source, mot pour mot
            yield from _textes_axe(v, k, dans or k in CLES_AXE)
    elif isinstance(x, list):
        for v in x:
            yield from _textes_axe(v, cle, dans)
    elif isinstance(x, str) and dans:
        yield cle, x


@pytest.mark.parametrize("nom", FICHIERS)
def test_textes_rediges_neutres(nom):
    doc = _lire(nom)
    erreurs = []
    for cle, t in list(textes(doc)) + list(_textes_axe(doc)):
        if cle == "citation":
            continue
        for raison in fautes(t):
            erreurs.append(f"[{cle}] {raison} : {t[:120]}")
        if JUGEMENTS.search(t):
            erreurs.append(f"[{cle}] jugement : {t[:120]}")
    assert not erreurs, "\n".join(erreurs[:20])


def test_le_filtre_de_jugements_fonctionne():
    for exemple in ("la chasse aux fraudeurs", "un niveau record", "des contrôles insuffisants", "une manne"):
        assert JUGEMENTS.search(exemple), exemple
    for neutre in ("Redressements à l'issue des contrôles d'assiette", "Montant notifié", "taux de recouvrement"):
        assert not JUGEMENTS.search(neutre), neutre


def test_aucune_personne_physique_ni_identifiant():
    cles_interdites = {"prenom", "nom_personne", "siren", "siret", "adresse", "courriel", "email", "telephone", "dirigeant",
                       "responsable", "contribuable", "cotisant", "raison_sociale"}
    for nom in FICHIERS:
        for chemin, cle, v in _parcourir(_lire(nom)):
            assert cle not in cles_interdites, (nom, chemin)
            if isinstance(v, str) and cle != "citation":
                assert not re.search(r"\b\d{9}\b|\b\d{14}\b|@[a-z0-9-]+\.[a-z]{2,}", v), (nom, chemin)


def test_sources_inaccessibles_et_recherche_publique(index):
    motifs = " ".join(s["motif"] for s in index["sources_inaccessibles"])
    assert "429" in motifs and "non insisté" in motifs
    verdicts = {t["verdict"] for t in index["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"} and len(verdicts) == 3
    for t in index["recherche_publique"]["trouvailles"]:
        assert t["licence"] and t["mise_a_jour"]


# ------------------------------------------------------------------------------------------------------------
# Fonctions de lecture (sans entrepôt)
# ------------------------------------------------------------------------------------------------------------

def test_valeurs_ligne_separe_milliers_et_colonnes():
    lu = rec.valeurs_ligne(["17", "2 778", "3 014", "2 289", "1 758", "961", "1 877", "2 231", "1 989", "2 080",
                            "4,55 %"], 9)
    assert lu == ([2778, 3014, 2289, 1758, 961, 1877, 2231, 1989, 2080], ["17"])
    lu = rec.valeurs_ligne(["IV.", "21", "1 494", "1 232", "940", "1 112", "1351", "2 018", "2 445", "2 694", "3 146",
                            "16,76 %"], 9)
    assert lu[0][4] == 1351 and lu[1] == ["IV.", "21"]
    assert rec.valeurs_ligne(["Encaissements du STDR", "2 476", "1 316", "939", "358", "0", "0", "0", "0", "0", "ns"],
                             9)[0] == [2476, 1316, 939, 358, 0, 0, 0, 0, 0]
    assert rec.valeurs_ligne(["B. Contrôle sur pièces"], 9) is None
    assert rec.valeurs_ligne(["12", "34"], 9) is None


def test_nombre_absent_est_none():
    assert rec._nombre("") is None and rec._nombre("-") is None and rec._nombre("nc") is None
    assert rec._nombre(None) is None and rec._nombre("0") == 0 and rec._nombre("1 234,5") == 1234.5
    assert rec._somme([None, None]) is None and rec._somme([None, 2.0, 3.0]) == 5.0
    assert rec._r(None) is None and rec._r(2.004) == 2.0 and rec._r(12.6, 0) == 13


def test_classement_des_lignes_d_annuaire():
    c = rec._classer_ligne_annuaire
    assert c(None, rec._cle("     I - Vérification de comptabilité")) == ("vc", None)
    assert c("vc", rec._cle("   - Impôt sur les sociétés (1)")) == ("vc", "vc_is")
    assert c("vc", rec._cle("Total des droits simples")) == ("vc", "vc_droits")
    assert c("vc", rec._cle("TOTAL (1)")) == ("vc", "vc_operations")
    assert c("vc", rec._cle("II - Examen contradictoire de la situation fiscale personnelle (ESFP)")) == ("esfp", None)
    assert c("esfp", rec._cle("RÉCAPITULATION DES RÉSULTATS DU CONTRÔLE SUR PLACE")) == ("place", None)
    assert c("place", rec._cle("2. Pénalités")) == ("place", "place_penalites")
    assert c("place", rec._cle("B - CONTRÔLE SUR PIÈCES (droits simples rappelés)")) == ("pieces", None)
    assert c("pieces", rec._cle("Impôt sur le revenu (4)")) == ("pieces", "pieces_ir")
    assert c("pieces", rec._cle("RÉCAPITULATION DES RÉSULTATS DU CONTRÔLE SUR PIÈCES")) == ("pieces", "pieces_droits")
    assert c("pieces", rec._cle("RÉCAPITULATION DES RÉSULTATS DU CONTRÔLE SUR PLACE ET SUR PIÈCES (droits simples)")
             ) == ("pieces", "total_droits")


def test_citation_retrouvee_malgre_les_coupures():
    page = "L’évaluation aboutit à un montant de fraudes\nde 14 Md€, contre 13 Md€ lors de l’évalua-\ntion précédente."
    assert rec.citation_presente("un montant de fraudes de 14 Md€, contre 13 Md€ lors de l'évaluation précédente",
                                 [page])
    assert not rec.citation_presente("un montant de fraudes de 15 Md€", [page])
    assert rec.nom_tri("Urssaf Île-de-France") == "urssaf ile-de-france"


# ------------------------------------------------------------------------------------------------------------
# Avec l'entrepôt : relecture des sources, citations, reproductibilité
# ------------------------------------------------------------------------------------------------------------

@entrepot
def test_citations_presentes_dans_les_documents_collectes(estimations):
    pytest.importorskip("pdfplumber")
    page_ce = [rec.texte_html(LAKE / rec.SOURCES["ce_ecart_tva_2025"]["fichier_collecte"])]
    for e in rec.ESTIMATIONS + rec.CONSTATS:
        t = page_ce if e["document"].endswith(".html") else rec.textes_page(e["document"], e["page"])
        assert rec.citation_presente(e["citation"], t), e["id"]
    v = estimations["verification_documents"]
    assert v["citations"] == v["retrouvees"] == len(rec.ESTIMATIONS) + len(rec.CONSTATS) + len(rec.SECURITE_SOCIALE)


@entrepot
def test_sommes_urssaf_relues_dans_le_csv(urssaf):
    lignes = rec._lire_csv("recouvrement_urssaf_controle.csv")
    for i, a in enumerate(urssaf["annees"]):
        for col, cle in (("montant_redressements", "redressements_eur"), ("montant_restitutions", "restitutions_eur")):
            s = sum(float(l[col]) for l in lignes if l["annee"][:4] == str(a) and l[col] != "")
            assert abs(s - urssaf["controle"]["total"][cle][i]) <= 1, (a, cle)


@entrepot
def test_production_reproductible(tmp_path):
    pytest.importorskip("pdfplumber")
    pytest.importorskip("xlrd")
    empreintes = []
    for graine in ("0", "4242"):
        sortie = tmp_path / graine
        env = {**os.environ, "PYTHONHASHSEED": graine}
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "recouvrement.py"), "produire", "--sortie",
                        str(sortie)], check=True, env=env, timeout=600)
        empreintes.append({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1] and set(empreintes[0]) == set(FICHIERS)
    for nom in FICHIERS:
        assert empreintes[0][nom] == hashlib.sha256((DATA / nom).read_bytes()).hexdigest(), nom
