"""Numérique de l'État (pipeline/numerique_etat.py) : rapprochement des noms, évolution publiée, fonds, liens à
l'arbre État, confidentialité, neutralité.

Les tests sur site/data/numerique_etat tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/numerique_etat), sautée sinon.
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
DATA = SITE / "numerique_etat"
LAKE = ROOT / "data" / "lake" / "numerique_etat"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import numerique_etat as ne  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

# Qualificatifs d'un écart de coût ou de délai (en plus du lexique partagé) : le site publie l'écart, sans le nommer.
JUGEMENTS = re.compile(r"(?<!\w)(?:d[ée]riv\w*|d[ée]rap\w*|surco[uû]t\w*|retards?|[ée]chec\w*|gouffre\w*|fiasco\w*|"
                       r"explos\w*|envol\w*|flamb\w*|dépassement\w*|trop|insuffisan\w*|excessi\w*|réussi\w*|"
                       r"succès|mauvais\w*|bon élève|alarmant\w*|inquiétant\w*)(?!\w)", re.I)
CLES_REDIGEES = {"avertissement", "note", "definitions", "methode", "regle", "regles", "limites", "raisons", "critere",
                 "usage", "rattachement", "regle_personnes", "par_annee_note", "ordre", "requetes", "libelle"}
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}|\b0\d(?:[ .]?\d{2}){4}\b|https?://|www\.", re.I)
CIVILITE = re.compile(r"\b(M\.|MM\.|Mme|Mlle|Mr|Monsieur|Madame|Mademoiselle)\s", re.I)


def lire(rel: str) -> dict:
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def projets() -> dict:
    return lire("panorama/projets.json")


@pytest.fixture(scope="module")
def editions() -> dict:
    return lire("panorama/editions.json")


@pytest.fixture(scope="module")
def index() -> dict:
    return lire("index.json")


# --- Fonctions de lecture (sans données) ---------------------------------------------------------------------------


@pytest.mark.parametrize("brut, attendu", [
    (38.7, (38.7, None)), ("53,02", (53.02, None)), (" 21 700,00 € ", (21700.0, None)), ("500000", (500000.0, None)),
    ("En cadrage", (None, "en cadrage")), ("NA", (None, "non communiqué")), ("Non communiqué", (None, "non communiqué")),
    (None, (None, "non publié")), ("", (None, "non publié")), ("Coach DINUM", (None, "non publié")),
])
def test_nombre_absence_jamais_zero(brut, attendu):
    assert ne.nombre(brut) == attendu


@pytest.mark.parametrize("brut, attendu", [
    ("avril 15", "2015-04"), ("janvier 2013", "2013-01"), ("décembre 17", "2017-12"), ("01/07/2011", "2011-07"),
    ("2014-10-01", "2014-10"), ("2014-10-01 00:00:00", "2014-10"), ("", None), (None, None), ("En cadrage", None),
])
def test_mois_debut_cinq_formes(brut, attendu):
    assert ne.mois_debut(brut) == attendu


def test_cle_nom_regle_r1():
    assert ne.cle_nom("Expadon 2") == ne.cle_nom("EXPADON 2")
    assert ne.cle_nom("Guichet_Entreprise_DGE") == ne.cle_nom("GUICHET ENTREPRISE DGE")
    assert ne.cle_nom("Géoportail") == ne.cle_nom("GEOPORTAIL")
    assert ne.cle_nom("CASSIOPEE") != ne.cle_nom("CASSIOPEE V2")
    assert ne.cle_nom("OPER@") != ne.cle_nom("OPERA")


def test_programmes_cites_numeros_publies_seulement():
    arbre = {"156": {"nom": "Gestion fiscale et financière de l'État et du secteur public local"},
             "218": {"nom": "Conduite et pilotage des politiques économiques et financières"}}
    par_nom = {ne.cle_nom(v["nom"]): k for k, v in arbre.items()}

    def nums(s):
        return [p["programme"] for p in ne.programmes_cites(s, arbre, par_nom)]

    assert nums("Programmes 156/349/218") == ["156", "218", "349"]
    assert nums("Police nationale (P176) à 80% / Administration territoriale (P307)") == ["176", "307"]
    assert nums("124 / 155") == ["124", "155"]
    assert nums("P302 P349") == ["302", "349"]
    assert nums("Programme national 216, 303 et 363 – Ministère de l'Intérieur") == ["216", "303", "363"]
    assert nums("Pour le HT2, P216 depuis le 01/01/2020, hors contribution de 100 M€") == ["216"]
    assert nums("Conduite et pilotage des politiques économiques et financières") == ["218"]
    assert nums("FMIS") == [] and nums("ONDAM") == [] and nums("") == []
    cite = ne.programmes_cites("Programme 999", arbre, par_nom)[0]
    assert cite["dans_arbre"] is False and cite["rattachement"] == "numéro publié"


def test_porteur_et_texte_filtrent_personnes_et_coordonnees():
    prenoms = {"JEAN", "MARIE", "THOMAS"}
    assert ne.porteur("COMMUNE DE LANNION [22300 LANNION]", prenoms) == "COMMUNE DE LANNION"
    assert ne.porteur("COMMUNE DE JEAN DUPONT VILLE", prenoms) == "COMMUNE DE JEAN DUPONT VILLE"  # forme institutionnelle
    assert ne.porteur("Jean Dupont", prenoms) is None
    assert ne.porteur("Mme Marie Durand, mairie", prenoms) is None
    assert ne.porteur("DSI contact@exemple.fr", prenoms) is None
    assert ne.porteur("", prenoms) is None
    assert ne.texte("Créée en 2014 par Thomas Martin, la plateforme", prenoms) is None
    assert ne.texte("Refonte du site www.exemple.fr", prenoms) is None
    assert ne.texte("Dématérialisation des autorisations d'urbanisme", prenoms) == "Dématérialisation des autorisations d'urbanisme"


def _releve(edition, nom, debut="2015-01", cout=10.0):
    return {"edition": edition, "nom": nom, "cle": ne.cle_nom(nom), "debut": debut, "cout_meur": cout}


def test_rapprochement_r2_criteres(monkeypatch):
    monkeypatch.setattr(ne, "RENOMMAGES", [
        ("Projet Alpha", "ALPHA", "sigle"),            # même début : rapproché, même si le coût change
        ("Beta V1", "BETA", "version"),                # même début, coût différent : non rapproché
        ("Gamma Cycle 1", "GAMMA", "version"),         # même début, même coût : rapproché
        ("Delta", "DELTA 2", "version"),               # éditions communes : non rapproché
        ("Epsilon", "EPSILON NG", "sigle"),            # débuts différents : non rapproché
        ("Zeta", "ZETA NG", "version"),                # coût non publié à la jonction : non rapproché
    ])
    releves = [
        _releve("2020-01", "Projet Alpha", cout=10.0), _releve("2020-06", "ALPHA", cout=14.0),
        _releve("2020-01", "Beta V1", cout=10.0), _releve("2020-06", "BETA", cout=14.0),
        _releve("2020-01", "Gamma Cycle 1", cout=10.0), _releve("2020-06", "GAMMA", cout=10.05),
        _releve("2020-01", "Delta"), _releve("2020-06", "Delta"), _releve("2020-06", "DELTA 2"),
        _releve("2020-01", "Epsilon", debut="2015-01"), _releve("2020-06", "EPSILON NG", debut="2019-03"),
        _releve("2020-01", "Zeta", cout=None), _releve("2020-06", "ZETA NG", cout=12.0),
        _releve("2020-01", "Expadon 2"), _releve("2020-06", "EXPADON 2"),
    ]
    lignees, appliques, refuses = ne.rapprocher(releves)
    assert lignees[ne.cle_nom("ALPHA")] == lignees[ne.cle_nom("Projet Alpha")]
    assert lignees[ne.cle_nom("GAMMA")] == lignees[ne.cle_nom("Gamma Cycle 1")]
    for a, b in (("Beta V1", "BETA"), ("Delta", "DELTA 2"), ("Epsilon", "EPSILON NG"), ("Zeta", "ZETA NG")):
        assert lignees[ne.cle_nom(a)] != lignees[ne.cle_nom(b)], a
    assert {r["ancien_nom"] for r in refuses} == {"Beta V1", "Delta", "Epsilon", "Zeta"}
    assert all(r["raisons"] for r in refuses)
    assert {tuple(r["noms"]) for r in appliques if r["regle"] == "R1"} == {("EXPADON 2", "Expadon 2")}
    assert {r["ancien_nom"] for r in appliques if r["regle"] == "R2"} == {"Projet Alpha", "Gamma Cycle 1"}


def test_meme_nom_deux_fois_dans_une_edition_fait_echouer():
    with pytest.raises(SystemExit):
        ne.rapprocher([_releve("2020-01", "Alpha"), _releve("2020-01", "ALPHA")])


def test_evolution_null_sous_deux_valeurs():
    assert ne.evolution([]) is None and ne.evolution([("2020-01", 5.0)]) is None
    e = ne.evolution([("2020-01", 40.0), ("2020-06", 55.0), ("2021-06", 50.0)])
    assert (e["ecart"], e["ecart_pct"], e["minimum"], e["maximum"], e["valeurs_publiees"]) == (10.0, 25.0, 40.0, 55.0, 3)


# --- Panorama publié -----------------------------------------------------------------------------------------------


def test_vingt_deux_editions_ordonnees(projets, editions, index):
    eds = [e["edition"] for e in editions["editions"]]
    assert len(eds) >= 22 and eds == sorted(set(eds)) and eds == projets["editions"]
    assert eds[0] == "2016-11" and eds[-1] >= "2025-12"
    assert [e["numero"] for e in editions["editions"]] == list(range(1, len(eds) + 1))
    assert index["panorama"]["editions"] == len(eds) and index["panorama"]["projets"] == len(projets["projets"])
    assert all(e["url"].startswith("https://static.data.gouv.fr/") for e in editions["editions"])


def test_releves_et_evolution_coherents(projets):
    ids = [p["id"] for p in projets["projets"]]
    assert len(ids) == len(set(ids))
    for p in projets["projets"]:
        rel = p["releves"]
        eds = [r["edition"] for r in rel]
        assert eds == sorted(set(eds)), p["id"]  # jamais deux lignes d'une même édition dans une lignée
        assert p["editions"] == {"nombre": len(rel), "premiere": eds[0], "derniere": eds[-1],
                                 "dans_la_derniere_edition": eds[-1] == projets["editions"][-1]}
        assert p["nom"] == rel[-1]["nom"] and set(p["noms_publies"]) == {r["nom"] for r in rel}
        for champ, mention, evo in (("cout_meur", "cout_mention", "evolution_cout_meur"),
                                    ("duree_ans", "duree_mention", "evolution_duree_ans")):
            for r in rel:
                assert (r[champ] is None) == (r[mention] is not None), (p["id"], r["edition"])
                assert r[champ] is None or r[champ] > 0
            pts = [(r["edition"], r[champ]) for r in rel if r[champ] is not None]
            e = p[evo]
            if len(pts) < 2:
                assert e is None, p["id"]
                continue
            assert (e["premiere"]["edition"], e["premiere"]["valeur"]) == pts[0]
            assert (e["derniere"]["edition"], e["derniere"]["valeur"]) == pts[-1]
            assert e["ecart"] == pytest.approx(pts[-1][1] - pts[0][1], abs=0.002)
            assert e["ecart_pct"] == pytest.approx((pts[-1][1] - pts[0][1]) / pts[0][1] * 100, abs=0.06)
            assert e["minimum"] == min(v for _, v in pts) and e["maximum"] == max(v for _, v in pts)


def test_rapprochements_documentes_et_ambigus_non_fusionnes(projets):
    par_nom = {}
    for p in projets["projets"]:
        for n in p["noms_publies"]:
            par_nom.setdefault(ne.cle_nom(n), set()).add(p["id"])
    assert all(len(v) == 1 for v in par_nom.values())  # un nom publié appartient à un seul projet
    assert {r["id"] for r in projets["methode"]["regles"]} == {"R1", "R2", "R3"}
    for r in projets["rapprochements"]:
        if r["regle"] == "R2":
            j = r["jonction"]
            assert par_nom[ne.cle_nom(r["ancien_nom"])] == par_nom[ne.cle_nom(r["nouveau_nom"])]
            assert j["debut_ancien"] == j["debut_nouveau"] is not None
            assert j["derniere_edition_ancien_nom"] < j["premiere_edition_nouveau_nom"]
            if r["type"] == "version":
                assert abs(j["cout_meur_ancien"] - j["cout_meur_nouveau"]) <= ne.TOLERANCE_COUT_MEUR
        else:
            assert len({ne.cle_nom(n) for n in r["noms"]}) == 1 and len(r["noms"]) > 1
    assert projets["non_rapproches"], "les changements ambigus sont publiés, pas fusionnés"
    for r in projets["non_rapproches"]:
        assert r["raisons"]
        assert par_nom[ne.cle_nom(r["ancien_nom"])] != par_nom[ne.cle_nom(r["nouveau_nom"])], r["ancien_nom"]
    # tout renommage déclaré est publié, appliqué ou non (hors ceux déjà réunis par un autre)
    declares = {(a, b) for a, b, _ in ne.RENOMMAGES}
    publies = {(r["ancien_nom"], r["nouveau_nom"]) for r in projets["rapprochements"] + projets["non_rapproches"]
               if r["regle"] == "R2"}
    assert publies <= declares and len(declares - publies) <= 2


def test_editions_egalent_la_somme_des_releves(projets, editions):
    par_ed = {}
    for p in projets["projets"]:
        for r in p["releves"]:
            par_ed.setdefault(r["edition"], []).append((p["id"], r))
    prec = None
    for e in editions["editions"]:
        lignes = par_ed[e["edition"]]
        couts = [r["cout_meur"] for _, r in lignes if r["cout_meur"] is not None]
        assert e["projets"] == len(lignes) and e["projets_sans_cout_publie"] == len(lignes) - len(couts)
        assert e["cout_publie_meur"] == pytest.approx(sum(couts), abs=0.01)
        assert sum(e["par_tranche"].values()) == len(lignes)
        assert sum(m["projets"] for m in e["par_ministere"]) == len(lignes)
        assert sum(m["cout_publie_meur"] or 0 for m in e["par_ministere"]) == pytest.approx(sum(couts), abs=0.05)
        actuels = {i for i, _ in lignes}
        if prec is None:
            assert e["entrants"] is None and e["sortants"] is None
        else:
            assert set(e["entrants"]) == actuels - prec and set(e["sortants"]) == prec - actuels
        prec = actuels
    assert [a["annee"] for a in editions["annees"]] == sorted({e["annee"] for e in editions["editions"]})


def test_ministeres_series_egalent_les_editions(editions):
    m = lire("panorama/ministeres.json")
    sigles = [x["ministere"] for x in m["ministeres"]]
    assert sigles == sorted(sigles)
    total = {}
    for x in m["ministeres"]:
        for s in x["editions"]:
            assert len(s["projets_ids"]) == s["projets"]
            total[s["edition"]] = total.get(s["edition"], 0) + s["projets"]
    assert total == {e["edition"]: e["projets"] for e in editions["editions"]}


def test_programmes_relies_aux_noeuds_de_l_arbre(projets):
    d = lire("panorama/programmes.json")
    ids = {p["id"] for p in projets["projets"]}
    assert sum(p["dans_arbre"] for p in d["programmes"]) >= 30
    for p in d["programmes"]:
        assert {x["id"] for x in p["projets"]} <= ids
        if p["dans_arbre"]:
            noeud = json.loads((SITE / p["fichier"]).read_text(encoding="utf-8"))
            assert noeud["niveau"] == "programme" and noeud["id"] == p["noeud"] and noeud["nom"] == p["nom"]
            assert noeud["id"].endswith("/" + p["programme"])
        else:
            assert p["noeud"] is None and p["fichier"] is None
    relies = {x["id"] for p in d["programmes"] for x in p["projets"]}
    assert relies | set(d["projets_sans_programme_relie"]) == ids
    assert not relies & set(d["projets_sans_programme_relie"])


# --- Fonds ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rel, cle_deps, dossier", [
    ("fonds/france_relance.json", ("departements",), "france_relance"),
    ("fonds/ditp.json", ("itn7_volet1", "departements"), "ditp_itn7"),
])
def test_departements_somme_et_fichiers(rel, cle_deps, dossier):
    doc = lire(rel)
    bloc = doc
    for c in cle_deps[:-1]:
        bloc = bloc[c]
    deps = bloc["departements"]
    codes = [d["code"] for d in deps if d["code"]]
    assert codes == sorted(codes) and len(codes) == len(set(codes)) >= 90
    total = bloc["total"]
    assert sum(d["projets"] for d in deps) == total["projets"]
    assert sum(d["montant_publie_eur"] or 0 for d in deps) == pytest.approx(total["montant_publie_eur"], abs=1)
    assert sum(d["projets_sans_montant_publie"] for d in deps) == total["projets_sans_montant_publie"]
    fichiers = {p.stem for p in (DATA / "fonds" / dossier).glob("*.json")}
    assert fichiers == set(codes)
    for d in deps:
        if not d["code"]:
            continue
        f = json.loads((SITE / d["fichier"]).read_text(encoding="utf-8"))
        assert f["departement"]["code"] == d["code"] and f["total"]["projets"] == len(f["projets"]) == d["projets"]
        publies = [p["montant_eur"] for p in f["projets"] if p["montant_eur"] is not None]
        assert f["total"]["projets_sans_montant_publie"] == len(f["projets"]) - len(publies)
        if publies:
            assert f["total"]["montant_publie_eur"] == pytest.approx(sum(publies), abs=0.5) == pytest.approx(
                d["montant_publie_eur"], abs=0.5)
        else:
            assert f["total"]["montant_publie_eur"] is None and d["montant_publie_eur"] is None  # jamais 0


def test_france_relance_ventilations_egalent_le_total():
    d = lire("fonds/france_relance.json")
    t = d["total"]
    assert t["projets"] > 4000 and 0 < t["projets_sans_montant_publie"] < t["projets"]
    for cle in ("par_dispositif", "par_ministere", "par_annee"):
        assert sum(x["projets"] for x in d[cle]) == t["projets"], cle
        assert sum(x["montant_publie_eur"] or 0 for x in d[cle]) == pytest.approx(t["montant_publie_eur"], abs=1), cle
        for x in d[cle]:  # un groupe sans aucun montant publié est null, jamais 0
            assert (x["montant_publie_eur"] is None) == (x["projets_sans_montant_publie"] == x["projets"]) or \
                x["montant_publie_eur"] == 0
    assert {x["annee"] for x in d["par_annee"]} == {2021, 2022}


def test_ftap_fast_ditp_totaux():
    f = lire("fonds/ftap.json")
    assert f["total"]["projets"] == len(f["laureats"]) >= 50 and f["par_annee"] is None and f["par_annee_note"]
    assert f["total"]["montant_publie_eur"] == pytest.approx(sum(x["montant_eur"] for x in f["laureats"]), abs=1)
    assert sum(x["projets"] for x in f["par_guichet"]) == len(f["laureats"])
    a = lire("fonds/fast.json")
    assert a["total"]["projets"] == len(a["projets"]) >= 90
    assert [x["numero"] for x in a["par_appel"]] == list(range(1, len(a["par_appel"]) + 1))
    assert sum(x["projets"] for x in a["par_appel"]) == sum(x["projets"] for x in a["par_annee"]) == len(a["projets"])
    assert a["total"]["montant_publie_eur"] == pytest.approx(sum(x["montant_eur"] or 0 for x in a["projets"]), abs=1)
    assert all(x["dont_coaching_eur"] is None or x["coaching_mention"] is None for x in a["projets"])
    d = lire("fonds/ditp.json")
    assert d["fitn8"]["total"]["projets"] == len(d["fitn8"]["projets"])
    assert sum(x["projets"] for x in d["fitn8"]["par_ministere"]) == len(d["fitn8"]["projets"])
    assert sum(x["projets"] for x in d["itn7_volet1"]["par_type"]) == d["itn7_volet1"]["total"]["projets"]


def test_fonds_relies_a_une_action_de_l_arbre(index):
    attendus = {"france_relance": "363-04", "ditp": "363-04", "ftap": "349-01", "fast": "352-01"}
    assert {f["id"]: f["arbre_etat"]["action"] for f in index["fonds"]} == attendus
    for f in index["fonds"]:
        a = f["arbre_etat"]
        noeud = json.loads((SITE / a["fichier"]).read_text(encoding="utf-8"))
        assert noeud["id"] == a["noeud"] and noeud["nom"] == a["nom_programme"]
        actions = {e["id"].rsplit("/", 1)[-1]: e["nom"] for e in noeud["enfants"]}
        assert actions[a["action"]] == a["nom_action"]
        assert (SITE / f["fichier"]).exists()
        assert lire(f["fichier"].removeprefix("numerique_etat/"))["arbre_etat"] == a


def test_annees_une_colonne_par_source(editions):
    a = lire("annees.json")
    annees = [x["annee"] for x in a["annees"]]
    assert annees == sorted(annees)
    par_an = {x["annee"]: x for x in a["annees"]}
    for e in editions["editions"]:
        assert e["edition"] in [p["edition"] for p in par_an[e["annee"]]["panorama_editions"]]
    fr = lire("fonds/france_relance.json")
    for x in fr["par_annee"]:
        assert par_an[x["annee"]]["france_relance_decisions"]["projets"] == x["projets"]
    assert not any("total" in x for x in a["annees"])  # aucune somme entre sources


# --- Règles transverses --------------------------------------------------------------------------------------------


def _chaines(x, cle=None):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _chaines(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v, cle)
    elif isinstance(x, str):
        yield cle, x


def _redigees(x, dans=False, cle=None):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _redigees(v, dans or k in CLES_REDIGEES, k)
    elif isinstance(x, list):
        for v in x:
            yield from _redigees(v, dans, cle)
    elif isinstance(x, str) and dans:
        yield cle, x


def test_entetes_tailles_et_dates():
    fichiers = sorted(DATA.rglob("*.json"))
    assert len(fichiers) > 150
    for f in fichiers:
        assert f.stat().st_size < 5_000_000, f.name
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"] and d["unite"], f.name
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["collecte_le"]), f.name
        assert "data.gouv.fr" in d["source"] or f.name in ("index.json", "annees.json"), f.name


def test_confidentialite_aucune_personne_ni_coordonnee():
    interdites = {"adresse", "courriel", "email", "telephone", "dirigeant", "responsable", "contact", "nom_prenom",
                  "prenom", "descriptif", "resume", "en_savoir_plus"}
    libres = {"porteur", "titre", "projet", "objet", "collectivite", "laureat", "description", "nom"}
    for f in sorted(DATA.rglob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))

        def cles(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    yield k
                    yield from cles(v)
            elif isinstance(x, list):
                for v in x:
                    yield from cles(v)

        assert not interdites & set(cles(d)), f.name
        for cle, s in _chaines(d):
            if cle in libres:
                assert not CONTACT.search(s), (f.name, cle, s[:80])
                assert not CIVILITE.search(s + " ") or "MESSIEURS" in s.upper(), (f.name, cle, s[:80])
            if cle in ("porteur", "collectivite"):
                assert not re.search(r"\[\d{5}", s), (f.name, s)  # code postal et commune du siège retirés
    fr = lire("fonds/france_relance.json")
    assert fr["confidentialite"]["titres_non_publies"] > 0  # le filtre a bien retiré des titres


def test_neutralite_aucun_qualificatif():
    erreurs = []
    for f in sorted(DATA.rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(doc):
            erreurs += [f"{f.name} [{cle}] {r} : {t[:80]}" for r in fautes(t)]
        for cle, t in _redigees(doc):
            erreurs += [f"{f.name} [{cle}] {r} : {t[:80]}" for r in fautes(t)]
            if JUGEMENTS.search(t):
                erreurs.append(f"{f.name} [{cle}] qualificatif : {t[:100]}")
    assert not erreurs, "\n".join(erreurs[:20])
    cles = set()
    for f in sorted(DATA.rglob("*.json")):
        cles |= set(re.findall(r'"([a-z_0-9]+)":', f.read_text(encoding="utf-8")))
    assert not [c for c in cles if JUGEMENTS.search(c.replace("_", " "))]
    p = lire("panorama/projets.json")
    assert "coût estimé publié" in p["avertissement"] and p["ordre"]["cles"] == ["nom", "edition"]


def test_recherche_publique_classee(index):
    tr = index["recherche_publique"]["trouvailles"]
    assert len(tr) >= 3
    for t in tr:
        assert t["verdict"] in {"réutilisable tel quel", "à adapter", "inspiration seulement"}
        assert t["licence"] and t["mise_a_jour"] and t["url"].startswith("https://")
    assert len(index["sources"]) == 5 and all(s["licence"] == "Licence Ouverte 2.0" for s in index["sources"])


def test_contrat_declare_les_fichiers_de_l_axe():
    sys.path.insert(0, str(ROOT / "docs"))
    import valider_contrat
    motifs = [m for s, m, _ in valider_contrat.FICHIERS if s.startswith("numerique_etat_")]
    assert len(motifs) == 12
    for f in sorted(DATA.rglob("*.json")):
        rel = f.relative_to(SITE).as_posix()
        assert any(Path(rel).match(m) and rel.count("/") == m.count("/") for m in motifs), rel
    assert "pipeline/numerique_etat.py" in (ROOT / "docs" / "contrat_interface.md").read_text(encoding="utf-8")


@pytest.mark.skipif(not (LAKE / "numerique_panorama_projets").exists(),
                    reason="entrepôt data/lake/numerique_etat absent : reproductibilité non vérifiable ici")
def test_production_reproductible_octet_pour_octet(tmp_path):
    empreintes = []
    for i, graine in enumerate(("0", "4242")):
        sortie = tmp_path / f"passe{i}"
        env = {**os.environ, "PYTHONHASHSEED": graine}
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "numerique_etat.py"), "produire", "--sortie",
                        str(sortie)], check=True, cwd=ROOT, env=env, capture_output=True)
        empreintes.append({p.relative_to(sortie).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(sortie.rglob("*.json"))})
    assert empreintes[0] == empreintes[1]
    publie = {p.relative_to(DATA).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(DATA.rglob("*.json"))}
    assert publie == empreintes[0], "site/data/numerique_etat n'est pas la sortie du pipeline sur cet entrepôt"


# --- Suivi édition par édition (écart à l'édition précédente, phase, ministère, programme) --------------------------


def test_ecart_precedent_fonction():
    rang = {"2020-01": 1, "2020-06": 2, "2021-01": 3}
    a = {"edition": "2020-01", "cout_meur": 40.0, "duree_ans": 3.0}
    b = {"edition": "2021-01", "cout_meur": 52.5, "duree_ans": None}
    assert ne.ecart_precedent(a, b, rang) == {"edition_precedente": "2020-01", "cout_meur": 12.5, "duree_ans": None,
                                              "editions_sans_le_projet_entre_les_deux": 1}


def test_suivi_edition_par_edition(projets):
    assert projets["calculs"]["calcule_par_le_site"] is True and "même projet" in projets["calculs"]["methode"]
    rang = {e: i for i, e in enumerate(projets["editions"])}
    for p in projets["projets"]:
        rel = p["releves"]
        assert rel[0]["ecart_precedent"] is None, p["id"]
        for avant, r in zip(rel, rel[1:]):
            e = r["ecart_precedent"]
            assert e["edition_precedente"] == avant["edition"]
            assert e["editions_sans_le_projet_entre_les_deux"] == rang[r["edition"]] - rang[avant["edition"]] - 1
            for champ in ("cout_meur", "duree_ans"):
                if avant[champ] is None or r[champ] is None:
                    assert e[champ] is None, (p["id"], r["edition"], champ)  # jamais 0 à la place d'une absence
                else:
                    assert e[champ] == pytest.approx(r[champ] - avant[champ], abs=0.002)
            assert (r["phase"] is None) == (r["phase_mention"] is not None), (p["id"], r["edition"])
        for evo in (p["evolution_cout_meur"], p["evolution_duree_ans"]):
            assert evo is None or evo["calcule_par_le_site"] is True


def test_rattachement_ministere_et_programme(projets):
    prog = lire("panorama/programmes.json")
    noms = {x["programme"]: x["nom"] for x in prog["programmes"]}
    for p in projets["projets"]:
        assert p["ministere_nom"] == p["releves"][-1]["ministere_nom"], p["id"]
        for x in p["programmes"]:
            assert x["nom"] == noms.get(x["programme"]), (p["id"], x["programme"])
            assert (x["nom"] is None) == (not x["dans_arbre"])
    # éditions sans colonne de phase : mention explicite, jamais une phase inventée
    sans_phase = {r["edition"] for p in projets["projets"] for r in p["releves"]
                  if r["phase_mention"] and "absente" in r["phase_mention"]}
    assert sans_phase and all(e >= "2025-06" for e in sans_phase)


def test_sommes_par_edition_signalees(editions):
    assert editions["calculs"]["calcule_par_le_site"] is True
    assert lire("panorama/ministeres.json")["calculs"]["calcule_par_le_site"] is True
