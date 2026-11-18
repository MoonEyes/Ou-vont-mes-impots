# tests/test_controle.py
"""Bloc contrôle (juridictions financières), influence (HATVP), aides aux entreprises : pipeline/controle.py."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SITE = RACINE / "site" / "data"
SORTIE = SITE / "controle"
sys.path.insert(0, str(RACINE / "pipeline"))
import controle  # noqa: E402

FICHIERS = sorted(SORTIE.rglob("*.json"))
pytestmark = pytest.mark.skipif(not (SORTIE / "index.json").exists(), reason="site/data/controle absent")


def charger(chemin):
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


# --- Fonctions pures -------------------------------------------------------------------------------------------------

def test_tranches_de_depense():
    assert controle.tranche_depense("< 10 000 euros") == (0.0, 10000.0)
    assert controle.tranche_depense("> = 100 000 euros et < 200 000 euros") == (100000.0, 200000.0)
    assert controle.tranche_depense("> = 10 000 000 euros") == (10000000.0, None)
    assert controle.tranche_depense(None) is None


def test_decoupage_des_cibles_ministerielles():
    connus = sorted(["Premier ministre", "Economie et finances", "Environnement, énergie et mer",
                     "Autres : à préciser"], key=len, reverse=True)
    assert controle.decouper_cibles("Premier ministre, Economie et finances, Environnement, énergie et mer",
                                    connus) == ["Premier ministre", "Economie et finances",
                                                "Environnement, énergie et mer"]
    assert controle.decouper_cibles("Economie et finances, Autres : à préciser", connus)[-1] == "Autres : à préciser"


def test_texte_avec_personne_ecarte():
    assert controle.texte_sans_personne("Réponse de M. Jean DUPONT, maire") is None
    assert controle.texte_sans_personne("Réponse de Mme Durand") is None
    assert controle.texte_sans_personne("La chambre a contrôlé les comptes de la commune.") is not None
    assert controle.cible_publiable("Autre : Jean DUPONT") == "texte libre non publié"


def test_constats_chiffres_du_resume():
    c = controle.constats_chiffres("Le déficit a atteint 155,9 Md€ en 2024. Rien ici.")
    assert c and c[0]["valeur_eur"] == pytest.approx(155.9e9)
    assert controle.constats_chiffres(None) == []


def test_demandeur_parlementaire_ne_rattache_pas_au_programme_511():
    progs = {"511": {"libelle": "Assemblée nationale", "mission": "Pouvoirs publics", "operateurs": []},
             "176": {"libelle": "Police nationale", "mission": "Sécurités", "operateurs": []}}
    assert controle.rattacher_programmes("Les politiques de lutte contre le tabagisme (Assemblée nationale)",
                                         progs)[0] == []
    assert controle.rattacher_programmes("Certification des comptes de l'Assemblée nationale", progs)[0] == ["511"]
    assert controle.rattacher_programmes("Les frais d'enquête dans la police nationale", progs)[0] == ["176"]


@pytest.mark.skipif(not (SITE / "local" / "geo" / "44.json").exists(), reason="référentiel géographique absent")
def test_codes_departement_et_epci():
    geo = controle.referentiel_geo()
    assert controle.code_departement(geo, "LOIRE-ATLANTIQUE, FRANCE") == "44"
    assert controle.code_departement(geo, "SAVOIE (FRANCE)") == "73"
    assert controle.code_departement(geo, "LOIRET (45)") == "45"
    assert controle.code_departement(geo, "COTES D ARMOR") == "22"
    r = controle.rattacher_collectivite(geo, "COMMUNE", "ABBARETZ", "ABBARETZ", "LOIRE-ATLANTIQUE")
    assert r["niveau"] == "commune" and r["codes"]["commune"] == "44001" and r["codes"]["epci"] == "244400537"
    r = controle.rattacher_collectivite(geo, "COMMUNAUTE DE COMMUNES", "COMMUNAUTE DE COMMUNES DE NOZAY", None,
                                        "LOIRE-ATLANTIQUE")
    assert r["niveau"] == "epci" and r["codes"]["epci"] == "244400537"


# --- Fichiers produits ---------------------------------------------------------------------------------------------

def test_entete_et_taille():
    assert FICHIERS
    for f in FICHIERS:
        d = charger(f)
        assert d.get("millesime") and d.get("source"), f
        assert f.stat().st_size < 5_000_000, f


def test_aucune_personne_physique():
    interdits = {"dirigeants", "collaborateurs", "clients", "prenom", "civilite", "emailDeContact",
                 "telephoneDeContact", "reponses", "auteur_reponse"}
    civ = re.compile(r"(?<![\w.])(M\.|Mme|Monsieur|Madame)\s+[A-ZÉ]")

    def parcourir(x, chemin):
        if isinstance(x, dict):
            for k, v in x.items():
                assert k not in interdits, f"{chemin}: clé {k}"
                parcourir(v, chemin)
        elif isinstance(x, list):
            for v in x:
                parcourir(v, chemin)
        elif isinstance(x, str):
            assert not civ.search(x), f"{chemin}: {x[:80]}"

    for f in FICHIERS:
        parcourir(charger(f), f.name)


def test_organisations_lobbying():
    d = charger(SORTIE / "lobbying" / "organisations.json")
    col = d["colonnes"]
    i_type, i_cat = col.index("type_identifiant"), col.index("categorie")
    for o in d["organisations"]:
        assert o[i_type] in ("SIREN", "RNA", "HATVP")
        assert o[i_cat] not in ("Travailleur indépendant", "Consultant indépendant", "Avocat indépendant")
        for an, bas, haut in o[col.index("depenses_declarees")]:
            assert haut is None or haut >= bas
    cache = controle.charger_sirene()
    if cache:
        for o in d["organisations"]:
            # cache partiel (runner GitHub à froid, résolution reprenable) : seules les entrées connues sont vérifiées
            if o[i_type] == "SIREN" and o[0] in cache:
                assert controle.sirene.personne_morale((cache[o[0]] or {}).get("cj")), o[0]
    assert d["exclus"]["organisations"] >= 0


def test_cibles_sans_personne_et_missions_connues():
    d = charger(SORTIE / "lobbying" / "ministeres.json")
    missions = {json.loads(f.read_text(encoding="utf-8"))["mission"]
                for f in (SITE / "realisations").glob("[0-9]*.json")}
    for c in d["cibles"]:
        assert set(c["missions_lolf"]) <= missions, c
    for m, x in d["correspondance_ministere_missions"].items():
        assert set(x["missions"]) <= missions, m


def test_collectivites_codes_coherents():
    for f in (SORTIE / "publications" / "collectivites").glob("*.json"):
        d = charger(f)
        assert d["departement"]["code"] == f.stem
        for p in d["publications"]:
            c = p["codes"]
            if not f.stem.startswith("region_"):
                assert c["departement"] == f.stem
            if c["commune"]:
                assert c["commune"][:2] == c["departement"][:2] or c["departement"].startswith("97")
        assert sum(d["comptes_par_niveau"].values()) == len(d["publications"])


def test_programmes_rattaches_existent():
    d = charger(SORTIE / "publications" / "programmes.json")
    ids = {p["id"] for p in d["publications"]}
    for p, x in d["programmes"].items():
        assert (SITE / "realisations" / f"{p}.json").exists()
        assert set(x["publications"]) <= ids
    for p in d["publications"]:
        assert p["programmes"] and p["rattachement"]


MOTS_EVALUATIFS = re.compile(r"\b(excessi|insuffisan|mauvais|gaspill|scandal|abusi|inefficac|efficace|"
                             r"exorbitant|opaque|colossa|énorme|dérive)", re.I)


def test_aides_estimations_jamais_tranchees():
    d = charger(SORTIE / "aides_entreprises.json")
    e = d["estimations"]
    assert len(e) >= 10
    for x in e:
        assert x["perimetre"] and x["source"] and x["annee_publication"]
        for champ in ("perimetre", "publication", "auteur", "composantes_note"):
            assert not MOTS_EVALUATIFS.search(x.get(champ) or ""), (x["id"], champ)
    assert d["fourchette"]["basse_md"] == min(x["md"] for x in e)
    assert d["fourchette"]["haute_md"] == max(x.get("md_haut") or x["md"] for x in e)
    assert not any(k in d for k in ("total_retenu", "estimation_retenue", "montant_officiel"))
    for x in e:
        if x.get("composantes_md"):
            assert sum(x["composantes_md"].values()) == pytest.approx(x["md"], abs=1)
    for l in d["donnees_du_site"]:
        assert (SITE / l["fichier"]).exists(), l["fichier"]
    v = d["verification_documents"]["estimations"]
    assert set(v.values()) <= {"vérifié", "document absent"}


def test_index_recherche_publique_et_sources():
    d = charger(SORTIE / "index.json")
    assert {r["verdict"] for r in d["recherche_publique"]} <= {"réutilisable tel quel", "à adapter",
                                                                "inspiration seulement"}
    assert all(r["licence"] and r["mise_a_jour"] for r in d["recherche_publique"])
    # data.ccomptes.fr injoignable et data.gouv.fr arrêté en 2019 : la raison de la lecture page par page est publiée
    assert any("data.ccomptes.fr" in s["source"] for s in d["sources_inaccessibles"])
    assert all(s["constat"] and s["effet"] for s in d["sources_inaccessibles"])
    for dep in d["controle"]["departements"]:
        assert (SITE / dep["fichier"]).exists()


# --- Rapports d'observations définitives des chambres régionales et territoriales (2020 à 2026) -----------------

PAGE = """<html><head><script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
{"@type": "Article", "headline": "Commune de Franconville - Cahier n°1 : contrôle organique (Val-d'Oise)",
 "about": ["Finances publiques", "fiscalité et gestion budgétaire", "CRC ÎLE-DE-FRANCE"],
 "description": "La chambre a contrôlé la commune.", "datePublished": "2025-09-01T10:00:00+0200"}]}</script>
<script>window.dataLayer = window.dataLayer || []; window.dataLayer.push({"titrePublication":"Commune de Franconville",
"idPublication":"79580","emetteurPublication":"CRC ÎLE-DE-FRANCE","documentPublication":"Rapport","institution":"CRC",
"thematique":"Finances publiques, fiscalité et gestion budgétaire"});</script></head><body>
<div class="left-side-elements"><p><span class="title-hover">CRC ÎLE-DE-FRANCE</span></p><span class="text-thematic">
<div class="thematic-wrap"><div><span class="title-hover"><a href="/publications?f%5B1%5D=thematic%3A17183">
<div class="field field--name-name"><div class="field__item">Finances publiques, fiscalité et gestion budgétaire</div>
</div></a></span></div></div></span><p><time class="date section" datetime="2025-09-01"> 01.09.2025 </time></p></div>
</article><script>{"currentPath":"node\\/79580"}</script>
<div class="links-with-buttons-inside"><div class="doc-type-icon"><a href="/sites/default/files/2025-09/IDR2025-12.pdf"
title="Rapport d'observations définitives" aria-hidden="true"></a></div><div class="side"><h2 class="title">Rapport
d'observations définitives</h2><div class="list-wrapper"><div class="list-item"> Date de communicabilité : 12.08.2025
</div><div class="list-item"> Date d'envoi : 11.06.2025 </div></div></div></div><div class="list-links-wrapper"></div>
<div class="links-with-buttons-inside"><div class="doc-type-icon"><a href="/fr/documents/1" title="Réponse de M. Jean
DUPONT, maire"></a></div></div>
<div class="links-with-buttons-inside"><div class="doc-type-icon"><a href="/fr/documents/2" title="Les éléments clés">
</a></div></div></body></html>"""


def test_extraction_page_rapport():
    x = controle.extraire_page("https://www.ccomptes.fr/fr/publications/commune-de-franconville", PAGE)
    assert x["titre"].startswith("Commune de Franconville") and x["juridiction"] == "CRC ÎLE-DE-FRANCE"
    assert x["institution"] == "CRC" and x["document_publication"] == "Rapport" and x["node"] == 79580
    assert x["themes"] == ["Finances publiques, fiscalité et gestion budgétaire"] and x["themes_id"] == [17183]
    assert x["date"] == "2025-09-01"
    types = [d["type"] for d in x["documents"]]
    assert types == ["Rapport d'observations définitives", "Les éléments clés"]  # réponse jamais gardée
    assert x["documents"][0]["infos"] == ["Date de communicabilité : 12.08.2025", "Date d'envoi : 11.06.2025"]
    assert controle.est_rod(x)
    assert not controle.est_rod({**x, "institution": "COUR", "juridiction": "Cour des comptes"})
    avis = {**x, "document_publication": "Avis", "documents": [{"type": "Avis de contrôle budgétaire", "url": "u"}]}
    assert not controle.est_rod(avis)


def test_ordre_de_lecture_reprise():
    plan = [("https://x/fr/publications/commune-de-a", "2026-01-02T00:00:00+01:00"),
            ("https://x/fr/publications/la-politique-b", "2026-03-01T00:00:00+01:00"),
            ("https://x/fr/publications/commune-de-c", "2018-05-01T00:00:00+02:00"),
            ("https://x/fr/publications/commune-de-d", "2025-06-01T00:00:00+02:00"),
            ("https://x/fr/publications/commune-de-e", "2024-06-01T00:00:00+02:00")]
    deja = {"https://x/fr/publications/commune-de-d": {"statut": 200, "lastmod_plan": "2025-01-01T00:00:00+01:00"},
            "https://x/fr/publications/commune-de-e": {"statut": 200, "lastmod_plan": "2024-06-01T00:00:00+02:00"}}
    o = [u.rsplit("/", 1)[-1] for u, _ in controle.ordre_de_lecture(plan, deja, "2020-01-01")]
    # jamais lues au nom d'un organisme, puis les autres, puis modifiées depuis la lecture, puis antérieures à 2020
    assert o == ["commune-de-a", "la-politique-b", "commune-de-d", "commune-de-c"]
    assert "commune-de-c" not in [u for u, _ in controle.ordre_de_lecture(plan, deja, "2020-01-01", anciennes=False)]


def test_cadence_espace_les_requetes():
    import time
    c = controle.Cadence(0.05)
    t0 = time.monotonic()
    for _ in range(5):
        c.attendre()
    assert time.monotonic() - t0 >= 0.19


class _Rep:
    def __init__(self, code, texte=""):
        self.status_code, self.text = code, texte


def _bac_collecte(tmp_path, monkeypatch, plan, reponses):
    """Collecte isolée : cache dans tmp_path, plan du site fixé, réponses HTTP simulées (dans l'ordre des appels)."""
    import requests
    for nom, chemin in (("CACHE_CC", tmp_path), ("PUBS", tmp_path / "publications.jsonl"),
                        ("SITEMAP", tmp_path / "plan.xml"), ("ETAT_COLLECTE", tmp_path / "etat.json"),
                        ("REFUS", tmp_path / "refus.json")):
        monkeypatch.setattr(controle, nom, chemin)
    monkeypatch.setattr(controle, "urls_sitemap", lambda **k: plan)
    appels = []

    def get(url, **k):
        appels.append(url)
        r = reponses(url, len(appels))
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(requests, "get", get)
    return appels


def test_collecte_arret_net_sur_403_puis_reprise(tmp_path, monkeypatch):
    plan = [(f"https://www.ccomptes.fr/fr/publications/commune-de-x{i}", f"2026-0{9 - i}-01T00:00:00+02:00")
            for i in range(4)]
    appels = _bac_collecte(tmp_path, monkeypatch, plan,
                           lambda u, n: _Rep(200, PAGE) if n == 1 else _Rep(403))
    b = controle.collecter_ccomptes(60, paralleles=1, pause_s=0.01, anciennes=False)
    assert len(appels) == 2, "aucune requête après le refus"
    assert "403" in b["arret"] and "non contourn" in b["arret"]
    assert "403" in json.loads((tmp_path / "refus.json").read_text(encoding="utf-8"))["motif"]
    assert len(controle.charger_pubs()) == 1 and b["restantes"] == 3
    # reprise : la page déjà lue n'est pas relue, le refus disparaît après un passage sans incident
    appels2 = _bac_collecte(tmp_path, monkeypatch, plan, lambda u, n: _Rep(200, PAGE))
    b2 = controle.collecter_ccomptes(60, paralleles=1, pause_s=0.01, anciennes=False)
    assert len(appels2) == 3 and plan[0][0] not in appels2
    assert b2["arret"] is None and b2["restantes"] == 0 and not (tmp_path / "refus.json").exists()


def test_collecte_arret_sur_429(tmp_path, monkeypatch):
    plan = [(f"https://www.ccomptes.fr/fr/publications/commune-de-y{i}", "2026-01-01T00:00:00+01:00") for i in range(3)]
    appels = _bac_collecte(tmp_path, monkeypatch, plan, lambda u, n: _Rep(429))
    b = controle.collecter_ccomptes(60, paralleles=1, pause_s=0.01, anciennes=False)
    assert len(appels) == 1 and "429" in b["arret"]


def test_collecte_serveur_indisponible_arret_note(tmp_path, monkeypatch):
    plan = [(f"https://www.ccomptes.fr/fr/publications/commune-de-z{i}", "2026-01-01T00:00:00+01:00") for i in range(9)]
    appels = _bac_collecte(tmp_path, monkeypatch, plan, lambda u, n: _Rep(503))
    b = controle.collecter_ccomptes(60, paralleles=1, pause_s=0.001, anciennes=False, max_echecs=2, max_pauses=2,
                                    essais=2, pause_incident_s=0.01, pause_essai_s=0.001)
    assert "serveur indisponible" in b["arret"] and len(appels) == 6 and not controle.charger_pubs()


def test_noms_de_personne_dans_les_intitules():
    assert controle.nom_de_personne_possible("Réponse de M. Jean DUPONT, maire")
    assert controle.nom_de_personne_possible("Gestion de fait : Jean DUPONT")
    assert controle.nom_de_personne_possible("Courrier de Mme Durand")
    for t in ("Association AIDAPHI (Cher, Indre, Loir-et-Cher, Loiret)", "Lycée Jean Moulin (Rhône)",
              "Commune de Saint-Jean-de-Luz", "Société villeurbannaise d’urbanisme (SVU) et la SAS « Totem SVU »"):
        assert not controle.nom_de_personne_possible(t), t


def test_choix_du_siren():
    req = {"cle": "x", "q": "Centre hospitalier de Cholet", "departement": "49"}
    res = [{"siren": "264900390", "nature_juridique": "7364", "nom_raison_sociale": "CENTRE HOSPITALIER DE CHOLET",
            "siege": {"departement": "49"}, "etat_administratif": "A"},
           {"siren": "994207850", "nature_juridique": "9220",
            "nom_raison_sociale": "ASSOCIATION DES INTERNES DU CENTRE HOSPITALIER DE CHOLET",
            "siege": {"departement": "49"}}]
    assert controle._choisir_siren(req, res) == {"siren": "264900390", "cj": "7364", "candidats": 1}
    autre_dep = [{**res[0], "siege": {"departement": "44"}}]
    assert controle._choisir_siren(req, autre_dep)["siren"] is None
    personne = [{**res[0], "nature_juridique": "1000"}]
    assert controle._choisir_siren(req, personne)["siren"] is None
    deux = [res[0], {**res[0], "siren": "111111111"}]
    assert controle._choisir_siren(req, deux)["siren"] is None


GEO = SITE / "local" / "geo" / "44.json"


@pytest.mark.skipif(not GEO.exists(), reason="référentiel géographique absent")
@pytest.mark.parametrize("titre,jur,attendu", [
    ("Commune de Franconville - Cahier n°1 : contrôle organique (Val-d'Oise)", "CRC ÎLE-DE-FRANCE",
     {"niveau": "commune", "commune": "95252", "departement": "95", "siren": "219502523"}),
    ("Centre Communal d'Action Sociale de Comines (Nord)", "CRC HAUTS-DE-FRANCE",
     {"niveau": "autre_organisme", "commune": "59152", "departement": "59"}),
    ("Commune de Lalinde (Dordogne)", "CRC NOUVELLE-AQUITAINE", {"niveau": "commune", "commune": "24223"}),
    ("Service départemental d'incendie et de secours du Calvados (SDIS 14)", "CRC NORMANDIE",
     {"niveau": "autre_organisme", "departement": "14", "commune": None}),
    ("Commune de Marseille (Bouches-du-Rhône) cahier n° 2 : situation financière", "CRC PROVENCE-ALPES-CÔTE D'AZUR",
     {"niveau": "commune", "commune": "13055"}),
    ("Centre communal d'action sociale de Lyon (Métropole de Lyon)", "CRC AUVERGNE-RHÔNE-ALPES",
     {"departement": "69", "commune": "69123"}),
    ("Région Bourgogne-Franche-Comté - alimentation durable", "CRC BOURGOGNE-FRANCHE-COMTÉ",
     {"niveau": "region", "departement": None, "region": "27"}),
    ("Commune de Takaroa (Polynésie française)", "CTC POLYNÉSIE FRANÇAISE",
     {"niveau": "autre_organisme", "departement": None, "region": None}),
])
def test_rattachement_d_un_rapport(titre, jur, attendu):
    geo = controle.referentiel_geo()
    a = controle.analyser_rod(geo, {"titre": titre, "juridiction": jur})
    obtenu = {**a["codes"], "niveau": a["niveau"], "siren": a["siren"]}
    assert {k: obtenu[k] for k in attendu} == attendu, a
    assert a["rattachement"]


@pytest.mark.skipif(not GEO.exists(), reason="référentiel géographique absent")
def test_memoire_publiee_redonne_la_meme_fiche(tmp_path, monkeypatch):
    """Un rapport publié, relu depuis le fichier publié (cache de collecte vide), redonne exactement la même fiche."""
    geo = controle.referentiel_geo()
    x = controle.extraire_page("https://www.ccomptes.fr/fr/publications/commune-de-franconville", PAGE)
    masque = {**x, "url": "https://www.ccomptes.fr/fr/publications/m", "node": 5,
              "titre": "Gestion de fait : Jean DUPONT (Val-d'Oise)"}
    fiches = [controle.fiche_rod(geo, p, {}, {}) for p in (x, masque)]
    assert fiches[1]["organisme"] is None and "non publié" in fiches[1]["titre"] and fiches[1]["siren"] is None
    monkeypatch.setattr(controle, "SORTIE_ROD", tmp_path)
    (tmp_path / "2025.json").write_text(json.dumps({"rapports": fiches}, ensure_ascii=False), encoding="utf-8")
    pages, _ = controle.memoire_rod()
    assert [controle.fiche_rod(geo, pages[f["url"]], {}, {}) for f in fiches] == fiches


# Fichiers publiés -------------------------------------------------------------------------------------------------

ROD = SORTIE / "rod_crtc"
ROD_ANNEES = sorted(ROD.glob("[0-9][0-9][0-9][0-9].json"))


@pytest.mark.skipif(not (ROD / "index.json").exists(), reason="rod_crtc absent")
def test_rod_fichiers_annuels():
    geo = {json.loads(f.read_text(encoding="utf-8"))["departement"]["code"]:
           (json.loads(f.read_text(encoding="utf-8")).get("region") or {}).get("code")
           for f in (SITE / "local" / "geo").glob("*.json")}
    vus = set()
    for f in ROD_ANNEES:
        d = charger(f)
        an = int(f.stem)
        assert d["annee"] == an and d["comptes"]["rapports"] == len(d["rapports"])
        dates = [r["date"] for r in d["rapports"]]
        assert dates == sorted(dates, reverse=True)
        for r in d["rapports"]:
            assert r["id"] not in vus
            vus.add(r["id"])
            assert r["annee"] == an and r["date"].startswith(str(an)) and "2020-01-01" <= r["date"] <= "2026-12-31"
            assert r["type"] == "Rapport d'observations définitives"
            assert r["url"].startswith("https://www.ccomptes.fr/") and r["juridiction"].split()[0] in ("CRC", "CTC",
                                                                                                    "CRTC")
            c = r["codes"]
            if c["departement"] and c["departement"] in geo:
                assert c["region"] == geo[c["departement"]], r["id"]
            if c["commune"]:
                assert c["commune"][:2] == c["departement"][:2], r["id"]
            if r["categorie_juridique"]:
                assert controle.sirene.personne_morale(r["categorie_juridique"]), r["id"]
            if r["organisme"] is None:  # intitulé non publié : rien qui identifie
                assert r["siren"] is None and "non publié" in r["titre"]
            else:
                assert not controle.nom_de_personne_possible(r["titre"]), r["id"]
            assert r["personne_morale"] in (True, None)
            assert (r["personne_morale"] is True) == bool(r["personne_morale_preuve"])
            assert not set(r) & {"resume", "description", "reponses", "auteur_reponse", "constats_chiffres"}


@pytest.mark.skipif(not (ROD / "index.json").exists(), reason="rod_crtc absent")
def test_rod_index_et_couverture():
    d = charger(ROD / "index.json")
    assert sorted(d["fichiers"]) == [f"controle/rod_crtc/{f.name}" for f in ROD_ANNEES]
    par_annee = {f.stem: len(charger(f)["rapports"]) for f in ROD_ANNEES}
    assert d["comptes"]["par_annee"] == par_annee and d["comptes"]["rapports"] == sum(par_annee.values())
    assert sum(d["comptes"]["par_chambre"].values()) == d["comptes"]["rapports"]
    c = d["couverture"]
    assert c["pages_modifiees_depuis_2020_lues"] + c["pages_modifiees_depuis_2020_restantes"] == \
        c["pages_modifiees_depuis_2020"] <= c["pages_au_plan_du_site"]
    idx = charger(SORTIE / "index.json")
    assert idx["rod_crtc"]["rapports"] == d["comptes"]["rapports"]


@pytest.mark.skipif(not (ROD / "index.json").exists(), reason="rod_crtc absent")
def test_rod_repris_dans_les_fichiers_par_departement():
    ids = defaultdict(set)
    for f in (SORTIE / "publications" / "collectivites").glob("*.json"):
        for p in charger(f)["publications"]:
            ids[f.stem].add(p["id"])
    for f in ROD_ANNEES:
        for r in charger(f)["rapports"]:
            dep = r["codes"]["departement"] or (f"region_{r['codes']['region']}" if r["codes"]["region"] else None)
            if dep:
                assert r["id"] in ids[dep], (r["id"], dep)


def test_ordre_relit_la_memoire_en_dernier():
    plan = [("https://x/fr/publications/commune-de-m", "2026-05-01T00:00:00+02:00"),
            ("https://x/fr/publications/commune-de-n", "2026-01-01T00:00:00+01:00")]
    deja = {"https://x/fr/publications/commune-de-m": {"statut": 200, "memoire": True}}
    o = [u.rsplit("/", 1)[-1] for u, _ in controle.ordre_de_lecture(plan, deja, "2020-01-01")]
    assert o == ["commune-de-n", "commune-de-m"]
    assert [u for u, _ in controle.ordre_de_lecture(plan, deja, "2020-01-01", relire_memoire=False)] == [plan[1][0]]


def test_memoire_des_publications_de_la_cour(tmp_path, monkeypatch):
    """Une publication de la Cour déjà publiée, cache de collecte vide : la même publication est reproduite."""
    pub = {"id": "cc-1234", "titre": "La politique de la ville", "date": "2024-03-01", "annee": 2024,
           "type": "Rapport public thématique", "juridiction": "Cour des comptes",
           "url": "https://www.ccomptes.fr/fr/publications/la-politique-de-la-ville",
           "url_document": "https://www.ccomptes.fr/sites/default/files/x.pdf", "constats_chiffres": [],
           "source": controle.SRC_PAGES}
    (tmp_path / "publications").mkdir()
    (tmp_path / "publications" / "autres.json").write_text(json.dumps({"publications": [pub]}), encoding="utf-8")
    monkeypatch.setattr(controle, "SORTIE", tmp_path)
    monkeypatch.setattr(controle, "SORTIE_ROD", tmp_path / "rod_crtc")
    monkeypatch.setattr(controle, "PUBS", tmp_path / "absent.jsonl")
    (lu,) = controle.lire_pages_ccomptes()
    assert {k: lu[k] for k in pub} == pub
    assert controle.pages_connues()[pub["url"]]["memoire"] is True
