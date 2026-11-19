"""Qui a voté tes impôts (pipeline/qui_a_vote.py, contrat 2.70) : rattachement impôt <-> texte et filtres (sans
réseau, sans entrepôt), puis contrôles des données publiées dans site/data/qui_a_vote/ (neutralité, personnes,
ordre, avertissements, cohérence avec le simulateur)."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import qui_a_vote as Q  # noqa: E402

DATA = ROOT / "site" / "data" / "qui_a_vote"


def imp(cits):
    return set(Q.impots_cites(cits))


# --- Citations d'articles de code --------------------------------------------------------------------------------------


def test_citation_explicite_et_listes():
    c = Q.citations(["I. – Au 1 du I de l’article 197 du code général des impôts, le montant est remplacé.",
                     "Les articles L. 136‑1‑1 et L. 136‑8 du code de la sécurité sociale sont ainsi modifiés :"])
    assert ("CGI", "197") in c and ("CSS", "L. 136-1-1") in c and ("CSS", "L. 136-8") in c


def test_citation_dans_un_bloc_le_code_est_ainsi_modifie():
    c = Q.citations(["I. – Le code général des impôts est ainsi modifié :",
                     "A. – À la première phrase du second alinéa de l’article 196 B, le montant est remplacé ;",
                     "B. – L’article 278‑0 bis est complété par un alinéa ;",
                     "II. – L’article 3 de la loi n° 2020-1721 du 29 décembre 2020 est abrogé."])
    assert ("CGI", "196 B") in c and ("CGI", "278-0 bis") in c
    assert not any(a == "3" for _, a in c)  # la section II ferme le bloc : l'article 3 d'une loi n'est pas du code


def test_gage_et_texte_insere_ignores():
    c = Q.citations(["I. – Au b septies de l’article 279 du code général des impôts, la date est remplacée.",
                     "II. – La perte de recettes pour l’État est compensée à due concurrence par la création d’une "
                     "taxe additionnelle aux droits mentionnés aux articles 575 et 575 A du code général des impôts.",
                     "« Art. L. 321-1. – Les articles L. 312-3 et L. 313-2 du code des impositions sur les biens et "
                     "services sont applicables. »"])
    assert c == [("CGI", "279")]
    assert imp(c) == {"tva"}


@pytest.mark.parametrize("cit, attendu", [
    (("CGI", "197"), {"impot_revenu"}), (("CGI", "204 H"), {"impot_revenu"}), (("CGI", "50-0"), {"impot_revenu"}),
    (("CGI", "158"), set()),                        # article large (dividendes...) : pas un paramètre du simulateur
    (("CGI", "278-0 bis"), {"tva"}), (("CGI", "298 sexdecies H"), {"tva"}), (("CGI", "299"), set()),
    (("CSS", "L. 136-8"), {"csg"}), (("CSS", "L. 136-1-1"), {"csg"}),
    (("CSS", "L. 136-7"), set()),                   # revenus de placement : non appliqués par le simulateur
    (("CIBS", "L. 312-35"), {"accises_energie"}), (("CIBS", "L. 314-4"), {"tabac"}), (("CGI", "575 A"), {"tabac"}),
    (("CIBS", "L. 313-28"), {"alcool"}), (("CSS", "L. 245-9"), {"alcool"}), (("CSS", "L. 245-13"), set()),
    (("CGI", "1388 quinquies"), {"taxe_fonciere"}), (("CGI", "1518 bis"), {"taxe_fonciere"}),
    (("CGI", "1522 bis"), {"teom"}), (("CRDS", "14"), {"crds"}), (("CRDS", "4"), set()),
])
def test_bases_legales_des_impots(cit, attendu):
    assert imp([cit]) == attendu


def test_intitule_nomme_l_impot_mais_pas_sa_destination():
    assert Q.impots_intitule("Indexation sur l’inflation du barème de l’impôt sur le revenu") == ["impot_revenu"]
    assert Q.impots_intitule("Adaptation des tarifs d’accise sur l’électricité") == ["accises_energie"]
    assert Q.impots_intitule("Stabilisation des fractions de taxe sur la valeur ajoutée affectées aux "
                             "collectivités") == []
    assert Q.impots_intitule("Modulation du fonds de compensation pour la taxe sur la valeur ajoutée") == []
    assert Q.impots_intitule("Instauration d'une contribution différentielle sur les hauts revenus") == []
    assert Q.impots_intitule(None) == []


def test_rattacher_article_entier_seulement_si_toutes_les_dispositions_relevent_de_l_impot():
    pur = Q.rattacher(None, ["I. – Le code général des impôts est ainsi modifié :", "1° L’article 197 est modifié ;",
                             "2° L’article 204 H est modifié."])
    assert pur["impot_revenu"]["methode"] == "code_cite" and pur["impot_revenu"]["article_entier"]
    mixte = Q.rattacher(None, ["I. – Le code général des impôts est ainsi modifié :", "1° L’article 197 est modifié ;",
                               "2° L’article 39 AH est abrogé ;", "3° L’article 261 A est modifié."])
    assert set(mixte) == {"impot_revenu", "tva"}
    assert not mixte["impot_revenu"]["article_entier"] and not mixte["tva"]["article_entier"]
    nomme = Q.rattacher("Réduction du plafond de l’abattement d’impôt sur le revenu des pensions",
                        ["I. – Le a du 5 de l’article 158 du code général des impôts est modifié."])
    assert nomme["impot_revenu"]["methode"] == "intitule" and nomme["impot_revenu"]["article_entier"]
    # même numéro en nouvelle lecture : l'intitulé du projet déposé n'est jamais une raison de relier...
    assert Q.rattacher(None, ["Le a du 5 de l’article 158 du code général des impôts est modifié."],
                       intitule_projet="Réduction de l’abattement d’impôt sur le revenu") == {}
    # ... mais il écarte un article d'affectation, même s'il cite le code
    assert Q.rattacher(None, ["L’article L. 312-107 du code des impositions sur les biens et services est modifié."],
                       intitule_projet="Dispositions relatives à l’affectation de ressources à des tiers") == {}


# --- Textes, lectures, scrutins -----------------------------------------------------------------------------------------

PROJET = """<p class="TOC">ARTICLE 2 : Indexation du barème de l’impôt sur le revenu</p>
<p class="TOC">ARTICLE 3 : Autre mesure</p>
<h6>ARTICLE<br/> 2 : Indexation du barème de l’impôt sur le revenu</h6>
<p>(1)</p><p>I. – Le code général des impôts est ainsi modifié :</p><p>A. – L’article 197 est ainsi modifié ;</p>
<p>Exposé des motifs</p><p>Le présent article cite l’article 278 du code général des impôts.</p>
<h6>ARTICLE 3 : Autre mesure</h6><p>L’article 3 de la loi n° 2020-1 est abrogé.</p>
<p>Article 3 bis (nouveau)</p><p>Au I de l’article 1388 du code général des impôts, le taux est modifié.</p>"""


def test_articles_du_texte_intitule_dispositif_sans_expose():
    a = Q.articles_du_texte(PROJET)
    assert a["2"]["intitule"] == "Indexation du barème de l’impôt sur le revenu"
    assert any("197" in l for l in a["2"]["alineas"]) and not any("278" in l for l in a["2"]["alineas"])
    assert "(1)" not in a["2"]["alineas"]
    assert a["3 bis"]["intitule"] is None and Q.rattacher(None, a["3 bis"]["alineas"]).keys() == {"taxe_fonciere"}


def test_lectures_et_etiquettes():
    docs = ["PRJLANR5L17B1906", "PRJLANR5L17B2247", "PRJLANR5L17BTC2400"]
    assert Q.lecture_de(docs, "PRJLANR5L17B1906") == "première lecture"
    assert Q.lecture_de(docs, "PRJLANR5L17B2247") == "nouvelle lecture"
    assert Q.lecture_de(docs, "PRJLANR5L17BTC2400") == "texte de la commission mixte paritaire"
    assert Q.etiquette("premier") == "1" and Q.etiquette("8", " QUATER") == "8 quater"
    assert Q.lecture_scrutin("l'article 5 du projet de loi de finances pour 2026 (nouvelle lecture).") == \
        "nouvelle lecture"
    assert Q.cle_texte("financement de la sécurité sociale", None, "2026") == "PLFSS 2026"
    assert Q.cle_texte("finances", "de fin de gestion", "2025") == "PLFG 2025"


def test_liste_des_impots_reprise_du_simulateur():
    hb = (ROOT / "web" / "src" / "calcul" / "hors-bulletin.ts").read_text(encoding="utf-8")
    bloc = re.search(r"LIBELLES_CONSO[^{]*\{(.*?)\}", hb, re.S).group(1)
    conso = set(re.findall(r"^\s*(\w+):", bloc, re.M))
    assert conso == set(Q.LIBELLES_CONSO_SIMULATEUR), "taxe sur la consommation du simulateur non couverte"
    ids = {i["id"] for i in Q.IMPOTS}
    assert set(Q.LIBELLES_CONSO_SIMULATEUR.values()) <= ids
    assert {"impot_revenu", "csg", "crds", "taxe_fonciere", "teom"} <= ids
    for x in ("id: 'taxe_fonciere'", "id: 'teom'", "'impot_revenu'", "'csg_crds'"):
        assert x in (hb + (ROOT / "web" / "src" / "calcul" / "types.ts").read_text(encoding="utf-8")), x


# --- Données publiées -------------------------------------------------------------------------------------------------

pytestmark_donnees = pytest.mark.skipif(not (DATA / "index.json").exists(), reason="site/data/qui_a_vote absent")
INTERDITS = re.compile(r"naissance|adresse|profession|patrimoine|hatvp|photo|courriel|email|telephone|sexe|civilite|"
                       r"age$|^age_|^ne_le|lieu_de_naissance", re.I)
QUALIFICATIFS = re.compile(r"taxeur|bon élève|mauvais élève|palmarès|classement des (?:députés|groupes)|meilleur|pire|"
                           r"score|champion", re.I)


def charger(nom):
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


def cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from cles(v)


def chaines(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from chaines(v)
    elif isinstance(x, str):
        yield x


def ordre_fr(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


@pytestmark_donnees
def test_index_impots_fichiers_et_avertissements():
    i = charger("index.json")
    assert [x["id"] for x in i["impots"]] == [x["id"] for x in Q.IMPOTS]
    for x in i["impots"]:
        assert (DATA / x["fichier"]).exists() and (DATA / x["fichier_votes"]).exists()
    texte = " ".join(i["avertissements"])
    for mot in ("n'est pas un vote sur l'impôt entier", "non-votant n'est pas forcément absent", "délégation",
                "mise au point"):
        assert mot in texte, mot
    assert "alphabétique" in i["regle_ordre_groupes"]
    assert i["comptes"]["scrutins_retenus"] > 0 and i["comptes"]["deputes_circonscriptions"] >= 577
    assert {d["code"] for d in i["departements"]} >= {"01", "44", "75", "2A", "2B", "971", "99"}
    assert i["non_couverts"] and i["non_couverts"][0]["motif"]
    for d in i["departements"]:
        assert (DATA / d["fichier"]).exists()


@pytestmark_donnees
def test_aucun_champ_personnel_interdit_ni_qualificatif():
    for f in sorted(DATA.rglob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        mauvais = sorted({k for k in cles(d) if INTERDITS.search(k)})
        assert not mauvais, (f.name, mauvais)
        if f.name.startswith(("index", "impot_")):
            redige = " ".join(v for k, v in ((k, d.get(k)) for k in ("methode", "presentation", "regle_ordre",
                                                                    "regle_personnes", "regle_ordre_groupes"))
                              if isinstance(v, str)) + " ".join(d.get("avertissements", []))
            assert not QUALIFICATIFS.search(redige), f.name
        assert f.stat().st_size < Q.LIMITE_OCTETS, f.name


@pytestmark_donnees
def test_scrutins_rattachement_source_et_groupes_par_ordre_alphabetique():
    for x in charger("index.json")["impots"]:
        d = charger(x["fichier"])
        v = charger(x["fichier_votes"])
        for s in d["scrutins"]:
            assert s["rattachement"]["preuves"] and s["url"].startswith("https://www.assemblee-nationale.fr/")
            noms = [g["groupe"] for g in s["groupes"]]
            assert noms == sorted(noms, key=ordre_fr), s["numero"]
            vg = v["votes"][str(s["numero"])]["groupes"]
            assert [g["groupe"] for g in vg] == noms
            for g, n in zip(s["groupes"], vg):  # listes nominatives = décompte publié par groupe
                assert (len(n["pour"]), len(n["contre"]), len(n["abstention"])) == (g["pour"], g["contre"],
                                                                                    g["abstentions"])
                for pos in ("pour", "contre", "abstention", "non_votant"):
                    assert n[pos] == sorted(n[pos], key=lambda pa: (ordre_fr(v["deputes"].get(pa) or "~"), pa)), pos
                    assert all(pa in v["deputes"] for pa in n[pos])
        for a in d["articles"]:
            assert a["rattachement"]["methode"] in ("intitule", "code_cite", "intitule_et_code_cite")
            if "intitule" in a["rattachement"]["methode"]:
                assert a["intitule_source"] == "texte examiné"


@pytestmark_donnees
def test_amendements_adoptes_nommes_et_ordonnes_par_date():
    for x in charger("index.json")["impots"]:
        d = charger(x["fichier"])
        dates = [a["date"] or "" for a in d["amendements_adoptes"]]
        assert dates == sorted(dates, reverse=True)
        for a in d["amendements_adoptes"]:
            assert a["sort"] == "Adopté" and a["url"].startswith("https://")
            au = a["auteur"]
            if au["type"] in ("député", "sénateur"):
                assert au["nom"] or au.get("masque"), a["numero"]
            if a["rattachement"]["methode"] == "article_vise":
                assert a["article_vise"]


@pytestmark_donnees
def test_ton_depute_circonscriptions_et_votes():
    i = charger("index.json")
    retenus = {s["numero"] for s in charger("scrutins.json")["scrutins"]}
    d = charger("departements/44.json")
    assert d["departement"] == {"code": "44", "nom": "Loire-Atlantique"}
    assert [c["numero"] for c in d["circonscriptions"]] == list(range(1, 11))
    for c in d["circonscriptions"]:
        assert c["deputes"]
        for x in c["deputes"]:
            assert set(x) <= {"depute", "nom", "masque", "debut", "fin", "votes"}
            for v in x["votes"]:
                assert v[0] in retenus and v[1] in ("pour", "contre", "abstention", "non_votant", None)
                assert x["debut"] <= next(s["date"] for s in charger("scrutins.json")["scrutins"] if s["numero"] == v[0])
    assert next(x for x in i["departements"] if x["code"] == "44")["circonscriptions"] == list(range(1, 11))
