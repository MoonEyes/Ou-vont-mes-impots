"""Aide au développement (pipeline/aide_developpement.py) : non-additivité, dons et prêts séparés, confidentialité.

Les tests sur site/data/aide_developpement tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/aide_developpement, data/lake/etat), sautée sinon.
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
DATA = SITE / "aide_developpement"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import aide_developpement as apd  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402

if not (DATA / "index.json").exists():
    pytest.skip("site/data/aide_developpement absent : lancer `python pipeline/aide_developpement.py produire`",
                allow_module_level=True)

FICHIERS = ["index", "apd_declaree", "afd", "ocde", "expertise_france", "proparco"]
DOCS = {n: json.loads((DATA / f"{n}.json").read_text(encoding="utf-8")) for n in FICHIERS}
INDEX = DOCS["index"]
# Aucune colonne ni clé ne réunit dons et prêts, ni plusieurs grandeurs.
CLE_TOTAL = re.compile(r"(^|_)(total|totale|ensemble|cumul|somme)(_|$)|dons_et_prets|prets_et_dons")


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            if isinstance(v, (dict, list)):
                yield from _cles(v)


def _colonnes(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k.startswith("colonnes") and isinstance(v, list):
                yield from v
            else:
                yield from _colonnes(v)
    elif isinstance(x, list):
        for v in x:
            yield from _colonnes(v)


def test_en_tete_source_et_taille():
    for n, d in DOCS.items():
        assert d["millesime"] and d["source"] and d["unite"], n
        assert "ne s'additionnent pas" in d["avertissement"], n
        assert (DATA / f"{n}.json").stat().st_size < 5_000_000, n
    assert {f["fichier"] for f in INDEX["fichiers"]} == {f"aide_developpement/{n}.json" for n in FICHIERS[1:]}
    for f in INDEX["fichiers"]:
        assert (SITE / f["fichier"]).exists(), f


def test_aucune_colonne_ne_reunit_dons_et_prets_ni_les_grandeurs():
    for n, d in DOCS.items():
        cols = list(_colonnes(d))
        fautives = [c for c in cols if CLE_TOTAL.search(c)]
        assert not fautives, (n, fautives)
    assert set(INDEX["totaux"]) == {"note", "apd_declaree", "afd", "ocde"}
    # une colonne par instrument, jamais de colonne commune
    assert INDEX["totaux"]["apd_declaree"]["colonnes"][1:3] == ["dons_verses_eur", "prets_verses_eur"]
    assert DOCS["afd"]["colonnes_montants"] == ["dons_engages_eur", "prets_engages_eur", "dons_verses_eur",
                                                "prets_verses_eur"]
    assert not [k for k in _cles(INDEX["totaux"]) if CLE_TOTAL.search(k)]


def test_six_grandeurs_decrites_producteur_perimetre_methode():
    ids = [g["id"] for g in INDEX["grandeurs"]]
    assert ids == ["credits_budgetaires", "apd_declaree", "afd", "proparco", "expertise_france", "ocde"]
    for g in INDEX["grandeurs"]:
        for k in ("producteur", "perimetre", "methode", "unite"):
            assert len(g[k]) >= 5, (g["id"], k)
        assert (SITE / g["fichier"]).exists(), g["id"]
        # aucun texte rédigé sur le financement : seulement des renvois vers des citations exactes
        assert g["financement"] is None, g["id"]
        assert set(g["financement_citations"]) <= {c["id"] for c in INDEX["citations"]}, g["id"]
    afd = next(g for g in INDEX["grandeurs"] if g["id"] == "afd")
    assert afd["financement_citations"] == INDEX["financement_des_prets"]["citations"] == apd.CIT_PRETS_AFD
    assert set(INDEX["financement_des_prets"]) == {"perimetre", "citations"}


def test_lien_avec_la_mission_budgetaire():
    vues = INDEX["credits_budgetaires"]["vues"]
    if not (SITE / "arbre" / "racine.json").exists():
        pytest.skip("arbre de l'État absent")
    assert vues and vues[0]["vue"] == "arbre"
    for v in vues:
        assert v["mission"]["nom"] == "Aide publique au développement"
        assert {"110", "209"} <= {p["numero"] for p in v["programmes"]}
        racine = json.loads((SITE / v["fichier_racine"]).read_text(encoding="utf-8"))
        missions = {m["id"]: m for poste in racine["enfants"] for m in poste["enfants"]}
        assert missions[v["mission"]["id"]]["md"] == v["mission"]["md"]
        assert abs(sum(p["md"] for p in v["programmes"]) - v["mission"]["md"]) < 0.001
        for p in v["programmes"]:
            assert p["fichier"] and (SITE / p["fichier"]).exists(), p


def test_apd_declaree_ventilations_coherentes():
    d = DOCS["apd_declaree"]
    assert d["annees"][0] == 2018 and d["annees"][-1] >= 2024
    codes = {p["code"] for p in d["pays"]}
    assert len(codes) == len(d["pays"]) and {l[1] for l in d["par_pays"]["lignes"]} <= codes
    assert [p["nom_tri"] for p in d["pays"]] == sorted(p["nom_tri"] for p in d["pays"])
    tot = {l[0]: l[1:] for l in INDEX["totaux"]["apd_declaree"]["lignes"]}
    for nom in ("par_canal", "par_agence", "par_secteur", "par_pays"):
        for a in d["annees"]:
            for i in (0, 1, 3):  # dons, prêts, équivalent-don : même somme quelle que soit la ventilation
                s = sum(l[2 + i] or 0 for l in d[nom]["lignes"] if l[0] == a)
                assert abs(s - tot[a][i]) <= len(d[nom]["lignes"]), (nom, a, i)
    # le flux APD de par_annee redonne les mêmes dons et prêts
    for a in d["annees"]:
        for fam, i in (("don", 0), ("pret", 1)):
            s = sum(l[5] or 0 for l in d["par_annee"]["lignes"]
                    if l[0] == a and l[1] == apd.FLUX_APD and l[3] == fam)
            assert abs(s - tot[a][i]) <= 50, (a, fam)
    for l in d["par_annee"]["lignes"]:
        assert l[3] == apd.FAMILLES.get(l[2], "autre")


def test_afd_dons_et_prets_par_annee_pays_secteur():
    d = DOCS["afd"]
    assert d["annees"][0] == apd.ANNEE_MIN_AFD and d["annees_partielles"]
    tri = {p["code"]: p["nom_tri"] for p in d["pays"]}
    assert {l[1] for l in d["par_pays"]["lignes"]} == set(tri)
    for a in d["annees"]:
        for flux in ("apd", "autres_apports_publics"):
            ref = [l for l in d["par_annee"]["lignes"] if l[0] == a and l[1] == flux]
            if not ref:
                continue
            for i in range(4):
                for nom in ("par_pays", "par_secteur"):
                    s = sum(l[3 + i] or 0 for l in d[nom]["lignes"] if l[0] == a and l[2] == flux)
                    assert abs(s - (ref[0][2 + i] or 0)) <= len(d[nom]["lignes"]), (a, flux, i, nom)
    assert [e for e in d["ecartes"] if "instantané" in e["motif"]][0]["activites"] > 0
    assert INDEX["totaux"]["afd"]["annees_partielles"] == d["annees_partielles"]
    assert not any(e["annee"] in d["annees_partielles"] for e in INDEX["ecarts"] if e["source"] == "afd_iati")


def test_ocde_dollars_non_convertis_et_identites():
    d = DOCS["ocde"]
    assert "dollars" in d["unite"] and "CC BY" in d["licence"]
    v = d["versements_par_pays"]
    col = {c: i for i, c in enumerate(v["ensemble_pays_en_developpement"]["colonnes"])}
    for l in v["ensemble_pays_en_developpement"]["lignes"]:
        brute, dons, prets = l[col["apd_brute_musd"]], l[col["dons_musd"]], l[col["prets_bruts_musd"]]
        assert abs(brute - dons - prets) / brute < 0.02, l  # identité publiée par l'OCDE, vérifiée, pas recalculée
        assert l[col["remboursements_prets_musd"]] <= 0
    assert all(re.fullmatch(r"[A-Z]{3}", p["code"]) for p in v["pays"]) and len(v["pays"]) > 100
    s = d["engagements_par_secteur"]
    niveaux = {x["code"]: x["niveau"] for x in s["secteurs"]}
    assert niveaux["1000"] == "total" and niveaux["110"] == "secteur" and niveaux["112"] == "sous_secteur"
    for l in s["lignes"]:
        if l[2] is not None and l[3] is not None:
            assert l[3] <= l[2] * 1.001 + 0.01, l  # « dont dons » ne dépasse pas les engagements


def test_ecarts_publies_et_recalculables():
    assert {e["source"] for e in INDEX["ecarts"]} == {"afd_iati", "ocde_dac2a"}
    for e in INDEX["ecarts"]:
        assert abs(e["montant"] - e["autre_montant"] - e["ecart"]) < 0.01
        assert abs(e["ecart_pct"] - (e["montant"] - e["autre_montant"]) / e["autre_montant"] * 100) < 0.06
        assert "publié tel quel" in e["lecture"]
        assert ("dons" in e["comparaison"]) != ("prêts" in e["comparaison"])  # un écart porte sur les dons ou sur les prêts


def test_expertise_france_agregats_sans_experts_individuels():
    d = DOCS["expertise_france"]
    assert {l[3] for l in d["lignes"]} == {"marche", "marche_subsequent", "subvention", "accord_cadre"}
    ecarte = [e for e in d["ecartes"] if "experts individuels" in e["motif"]]
    assert len(ecarte) == 1 and ecarte[0]["contrats"] > 0
    assert "plafond" in d["definitions"]["accord_cadre"] and "pas une dépense" in d["avertissement"]
    for nom, i in (("par_bailleur", 2), ("par_pays", 1)):
        for l in d[nom]["lignes"]:
            contrats = sum(x[4] for x in d["lignes"] if x[i] == l[0] and x[3] != "accord_cadre")
            cadres = sum(x[4] for x in d["lignes"] if x[i] == l[0] and x[3] == "accord_cadre")
            assert (contrats, cadres) == (l[1], l[3]), (nom, l[0])
    # seuls des pays, « Plusieurs pays » ou « Non renseigné » ; seuls les bailleurs institutionnels de la source
    assert not [l[1] for l in d["lignes"] if "," in l[1]]
    assert len({l[2] for l in d["lignes"]}) < 30


def test_aucune_personne_ni_texte_libre_publie():
    interdites = {"attributaires", "attributaire", "beneficiaire", "beneficiaires", "nom_du_client", "client",
                  "objet", "objet_du_contrat", "titre", "intitule", "intitule_du_projet", "description", "email",
                  "courriel", "contact", "telephone", "adresse", "prenom", "expert", "iati_identifier", "identifiant"}
    for n, d in DOCS.items():
        assert not (set(_cles(d)) | set(_colonnes(d))) & interdites, n
        brut = (DATA / f"{n}.json").read_text(encoding="utf-8")
        assert "@" not in brut.replace("DSD_DAC2@DF_DAC2A", "").replace("DSD_DAC1@DF_DAC5", ""), n
        assert not re.search(r"FR-3-[A-Z]{3}\d", brut), n  # aucun identifiant de projet de l'AFD
    # le module ne lit jamais les colonnes nominatives ni les textes libres des sources
    source = (ROOT / "pipeline" / "aide_developpement.py").read_text(encoding="utf-8")
    for colonne in ("attributaires", "objet_du_contrat", "intitule_du_projet", "nom_du_client", "titre_du_projet",
                    "resume_du_projet", "presentation_du_client", "description_courte", "numero_de_projet",
                    "contact-info", "participating-org", "narrative"):
        assert not re.search(rf"""(get|\[|find\w*)\(?\s*["']{colonne}["']""", source), colonne
    assert set(apd.COLONNES_ETAT).isdisjoint({"description", "description_courte", "numero_de_projet",
                                              "num_identification_snpc", "mots_cles", "localisation_geographique"})


def test_ordre_alphabetique_et_absences():
    for n in ("apd_declaree", "afd", "expertise_france", "proparco"):
        assert "aucun classement par montant" in DOCS[n]["ordre"]["regle"], n
    ef = DOCS["expertise_france"]["lignes"]
    cles = [(l[0] is None, l[0] or 0, apd.nom_tri(l[1]), apd.nom_tri(l[2]), l[3]) for l in ef]
    assert cles == sorted(cles)
    pr = DOCS["proparco"]["par_annee"]["lignes"]
    assert [l[:2] for l in pr] == sorted(l[:2] for l in pr)
    # une valeur absente est null : la colonne « autres » de l'APD déclarée 2023 n'existe pas à la source
    assert any(None in l for l in DOCS["apd_declaree"]["par_pays"]["lignes"])


def test_textes_neutres():
    juge = re.compile(r"(?<!\w)(?:généro\w*|charité|gaspill\w*|trop|insuffisan\w*|excessi\w*|meilleur\w*|pire\w*|"
                      r"corrompu\w*|dilapid\w*)(?!\w)", re.I)
    for n, d in DOCS.items():
        for cle, t in textes(d):
            assert not fautes(t), (n, cle, t[:100])
            assert not juge.search(t), (n, cle, t[:100])
        for cle in ("avertissement",):
            assert not juge.search(d[cle]), n


def test_sources_licences_et_recherche_publique():
    ids = {s["id"] for s in INDEX["sources"]}
    assert ids == set(apd.SOURCES)
    cat = {s["id"]: s for s in json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))["sources"]}
    for sid in ids:
        assert sid in cat, sid
    assert cat["apd_expertise_france_contrats"].get("personnes_physiques") is True
    for s in INDEX["sources"]:
        assert s["licence"] and s["url"].startswith("https://"), s["id"]
    assert INDEX["sources_inaccessibles"] and "403" in INDEX["sources_inaccessibles"][0]["constat"]
    verdicts = {t["verdict"] for t in INDEX["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"} and len(verdicts) == 3


def test_iso_et_instruments_unitaires():
    assert len(set(apd.ISO2_ISO3.values())) == len(apd.ISO2_ISO3)
    assert all(re.fullmatch(r"[A-Z]{2}", k) and re.fullmatch(r"[A-Z]{3}", v) for k, v in apd.ISO2_ISO3.items())
    assert apd.ISO2_ISO3["SN"] == "SEN" and apd.ISO2_ISO3["CD"] == "COD" and apd.ISO2_ISO3["CG"] == "COG"
    for t, attendu in (("Prêt", "pret"), ("prêt durable", "pret"), ("Prise de participation", "participation"),
                       ("Garantie", "garantie"), ("Gar Donnée", "garantie"), ("Subvention", "don"), ("", "non_renseigne")):
        assert apd._instrument_proparco(t) == attendu, t
    c = apd.Cumul()
    c.ajouter("a", None)
    c.ajouter("a", float("nan"))
    assert c.get("a") is None
    c.ajouter("a", 0.4)
    assert apd._eur(c.get("a")) == 0 and apd._eur(None) is None


ENTREES = [apd.F_ETAT, apd.D_IATI, apd.F_DAC2A, apd.F_DAC5, apd.F_EF, apd.F_PROPARCO]


@pytest.mark.skipif(not all(p.exists() for p in ENTREES), reason="entrepôt data/lake incomplet pour cet axe")
def test_production_reproductible_octet_pour_octet(tmp_path):
    empreintes = []
    for graine in ("1", "2"):
        sortie = tmp_path / graine
        env = {k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}
        env["PYTHONHASHSEED"] = graine
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "aide_developpement.py"), "produire", "--sortie",
                        str(sortie)], check=True, env=env, cwd=ROOT)
        empreintes.append({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1] and len(empreintes[0]) == len(FICHIERS)
    publie = {f"{n}.json": hashlib.sha256((DATA / f"{n}.json").read_bytes()).hexdigest() for n in FICHIERS}
    assert empreintes[0] == publie, "site/data/aide_developpement n'est pas la sortie de l'entrepôt courant"


# ------------------------------------------------------------------ textes explicatifs : une source pour chacun

CLES_TEXTE = re.compile(r"^(avertissement|notes?|explications?|lecture|constat|texte|financement|limites|regle|"
                        r"regle_personnes|ecarts_note|perimetre\w*|methode|motif|definitions|commentaire|"
                        r"interpretation|precision)$")
# affirmations sur le financement de l'aide déjà publiées sans source : interdites hors citation exacte
AFFIRMATION_SANS_SOURCE = re.compile(
    r"(?:non|pas|jamais)\s+(?:financ\w+\s+)?(?:par|sur)\s+(?:l['’]|les\s+|des\s+)?(?:imp[ôo]ts?|contribuables?|"
    r"crédits\s+budgétaires)|ne\s+viennent\s+pas\s+du\s+budget|sans\s+(?:recours\s+à\s+)?l['’]imp[ôo]t|"
    r"remboursés\s+par\s+les\s+emprunteurs|ressources\s+empruntées", re.I)


def _chemins_texte(x, chemin=()):
    """Réimplémentation indépendante du pipeline : motifs des champs texte explicatifs non vides."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "sources_textes":
                continue
            c = chemin + (k,)
            if CLES_TEXTE.match(k):
                if isinstance(v, str):
                    if v.strip():
                        yield "/".join(c)
                    continue
                if isinstance(v, list) and all(isinstance(e, str) for e in v):
                    if any(e.strip() for e in v):
                        yield "/".join(c + ("*",))
                    continue
                if isinstance(v, dict) and all(isinstance(e, str) for e in v.values()):
                    if any(e.strip() for e in v.values()):
                        yield "/".join(c + ("*",))
                    continue
            yield from _chemins_texte(v, c)
    elif isinstance(x, list):
        for v in x:
            yield from _chemins_texte(v, chemin + ("*",))


def _toutes_chaines(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _toutes_chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _toutes_chaines(v)
    elif isinstance(x, str):
        yield x


def test_chaque_champ_texte_explicatif_a_une_source():
    """Échoue si un champ texte explicatif de l'axe (avertissement, note, lecture, constat, limites, définitions…)
    n'a pas de source associée dans sources_textes, ou si cette source n'existe pas."""
    ids_sources = {s["id"] for s in INDEX["sources"]}
    ids_citations = {c["id"] for c in INDEX["citations"]}
    for n, d in DOCS.items():
        st = d["sources_textes"]
        chemins = set(_chemins_texte(d))
        manquants = sorted(chemins - set(st))
        assert not manquants, (n, "champs texte sans source", manquants)
        assert set(st) == chemins, (n, "sources déclarées pour des champs absents", sorted(set(st) - chemins))
        cites_ici = {c["id"] for c in d.get("citations", [])}
        for chemin, refs in st.items():
            assert refs, (n, chemin)
            for r in refs:
                if r == "citation":
                    assert chemin == "citations/*/texte", (n, chemin)
                elif r.startswith("citation:"):
                    assert r[9:] in ids_citations and (n == "index" or r[9:] in cites_ici), (n, chemin, r)
                else:
                    assert r in {"traitement", "arbre"} | ids_sources, (n, chemin, r)


def test_citations_exactes_avec_adresse_et_date():
    assert {c["id"] for c in INDEX["citations"]} == {c["id"] for c in apd.CITATIONS}
    par_id = {c["id"]: c for c in INDEX["citations"]}
    for n, d in DOCS.items():
        for c in d.get("citations", []):
            assert c == par_id[c["id"]], (n, c["id"])  # même citation partout
            assert c["url"].startswith("https://") and c["auteur"] and c["document"] and len(c["texte"]) > 20, c
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["consulte_le"]), c
            assert c["page"] is None or (isinstance(c["page"], int) and c["page"] > 0), c
    # les citations du projet annuel de performances donnent leur page
    assert all(c["page"] for c in INDEX["citations"] if "PAP2026" in c["url"])


def test_aucune_affirmation_non_sourcee_sur_le_financement():
    textes_cites = {c["texte"] for c in INDEX["citations"]}
    for n, d in DOCS.items():
        for t in _toutes_chaines(d):
            if t in textes_cites:
                continue
            assert not AFFIRMATION_SANS_SOURCE.search(t), (n, t[:160])
    assert not hasattr(apd, "FINANCEMENT_PRETS")
