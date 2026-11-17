"""Collectivités d'outre-mer (pipeline/outremer.py) : cohérence des fichiers publiés et fonctions de lecture, sans réseau."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "outremer"
sys.path.insert(0, str(ROOT / "pipeline"))
import outremer  # noqa: E402

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/outremer absent : lancer `python pipeline/outremer.py produire`", allow_module_level=True)

INDEX = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
CODES = ["975", "977", "978", "986", "987", "988"]
FICHES = {c: json.loads((DOSSIER / f"{c}.json").read_text(encoding="utf-8")) for c in CODES}
NC = json.loads((DOSSIER / "988_budget.json").read_text(encoding="utf-8"))
PUBLIE, NON_PUBLIE = "publié", "non publié en données ouvertes"


# --- couverture et statuts ----------------------------------------------------------------------------------------

def test_six_territoires_avec_leurs_communes():
    assert [t["code"] for t in INDEX["territoires"]] == CODES
    attendu = {"975": 2, "977": 1, "978": 1, "986": 3, "987": 48, "988": 33}
    for c, f in FICHES.items():
        assert len(f["communes"]) == attendu[c] == f["territoire"]["communes"], c
        assert all(i.startswith(c) for i in f["communes"]), c
        assert f["territoire"]["population"] == sum(x["population"] for x in f["communes"].values()), c


def test_territoires_absents_de_local_et_local_non_modifie():
    """Le module complète local/ sans le toucher : aucun des six codes n'y figure."""
    for c in CODES:
        assert not (SITE / "local" / "geo" / f"{c}.json").exists(), c
    source = (ROOT / "pipeline" / "outremer.py").read_text(encoding="utf-8")
    assert not re.search(r'SITE\s*/\s*"local"', source) and "import local" not in source


def test_chaque_bloc_a_un_statut_jamais_vide_ni_estime():
    blocs = set(INDEX["blocs"])
    assert set(INDEX["statuts"]) == {PUBLIE, NON_PUBLIE}
    for c, f in FICHES.items():
        assert set(f["blocs"]) == blocs, c
        for nom, b in f["blocs"].items():
            assert b["statut"] in (PUBLIE, NON_PUBLIE), (c, nom)
            if b["statut"] == NON_PUBLIE:
                assert len(b["motif"]) > 20 and "source" not in b, (c, nom)
            else:
                assert b["source"] in INDEX["sources"], (c, nom)
        t = next(x for x in INDEX["territoires"] if x["code"] == c)
        assert t["blocs"] == {n: b["statut"] for n, b in f["blocs"].items()}, c


def test_blocs_absents_declares_non_publies():
    for c, f in FICHES.items():
        assert f["budget_communes"]["statut"] == NON_PUBLIE and f["budget_communes"]["motif"], c
        assert set(f["budget_communes"]) == {"statut", "motif"}, c
    for c in ("975", "977", "978", "986", "987"):
        assert FICHES[c]["budget_collectivite"] == {"statut": NON_PUBLIE,
                                                    "motif": FICHES[c]["blocs"]["budget_collectivite"]["motif"]}, c
        assert FICHES[c]["blocs"]["impots_territoriaux"]["statut"] == NON_PUBLIE, c
    for c in ("977", "978"):
        assert FICHES[c]["dotations_communes"]["statut"] == NON_PUBLIE, c
    assert FICHES["977"]["dotations_collectivite"]["statut"] == NON_PUBLIE
    assert "PDF" in FICHES["987"]["budget_collectivite"]["motif"]
    assert FICHES["988"]["budget_collectivite"]["statut"] == PUBLIE


def test_non_publie_ne_porte_aucune_donnee():
    """Un bloc non publié ne contient que son statut et son motif : aucun nombre."""
    def nombres(x):
        if isinstance(x, dict):
            return any(nombres(v) for v in x.values())
        if isinstance(x, list):
            return any(nombres(v) for v in x)
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    for c, f in FICHES.items():
        for cle in ("dotations_communes", "dotations_intercommunalites", "dotations_collectivite",
                    "budget_collectivite", "budget_communes"):
            if f[cle]["statut"] == NON_PUBLIE:
                assert not nombres(f[cle]), (c, cle)


# --- dotations --------------------------------------------------------------------------------------------------

def test_dotations_au_format_de_local():
    """Mêmes clés que local/dotations/communes : communes.<insee> = {nom, eur.<annee>.<cle>}."""
    local = sorted((SITE / "local" / "dotations" / "communes").glob("*.json"))
    cles_local = set(json.loads(local[0].read_text(encoding="utf-8"))["cles"]) if local else set()
    for c in ("975", "986", "987", "988"):
        d = FICHES[c]["dotations_communes"]
        assert d["statut"] == PUBLIE and d["unite"] == "euros" and d["annees"][0] == "2018", c
        assert set(d["communes"]) <= set(FICHES[c]["communes"]), c
        assert set(d["cles"]) <= cles_local | {"dgf_dacom", "dpel"} or not cles_local, (c, d["cles"])
        for insee, x in d["communes"].items():
            assert set(x) == {"nom", "eur"} and set(x["eur"]) <= set(d["annees"]), insee
            for an, v in x["eur"].items():
                assert v and all(isinstance(m, int) for m in v.values()), (insee, an)
    assert len(FICHES["988"]["dotations_communes"]["communes"]) == 33
    assert len(FICHES["987"]["dotations_communes"]["communes"]) == 48
    assert len(FICHES["987"]["dotations_intercommunalites"]["epci"]) == 7


def test_dotations_collectivites_975_et_978():
    for c in ("975", "978"):
        d = FICHES[c]["dotations_collectivite"]
        assert d["statut"] == PUBLIE and "2025" in d["eur"], c
        for an, v in d["eur"].items():
            parts = [v.get(k, 0) for k in ("dgf_forfaitaire", "dgf_compensation", "dgf_perequation_urbaine",
                                           "dgf_fonctionnement_minimale")]
            assert abs(sum(parts) - v["dgf_totale"]) <= 2, (c, an)
        assert d["recettes_reelles_fonctionnement_n_moins_2"]["eur"], c


# --- crédits de l'État ------------------------------------------------------------------------------------------

def test_cour_des_comptes_2018_2020_et_licence_odbl():
    assert "ODbL" in INDEX["sources"]["cour_des_comptes"]["licence"]
    for c, f in FICHES.items():
        x = f["credits_etat"]["cour_des_comptes_2018_2020"]
        assert "ODbL" in x["licence"] and set(x["annees"]) == {"2018", "2019", "2020"}, c
        cp, pop = x["annees"]["2018"]["execution_cp_eur"], x["population_2018"]
        assert abs(cp / pop - x["cp_executes_par_habitant_eur"]["2018"]) < 0.01, c  # montants en euros, pas en M€
        assert x["cp_executes_par_habitant_eur"]["2019"] is None, c  # non publié par la Cour : null, pas 0


def test_dpt_publie_seulement_si_les_sommes_se_verifient():
    assert INDEX["credits_etat_plf2026"]["territoires_lus"]
    for c, f in FICHES.items():
        d = f["credits_etat"]["dpt_plf2026"]
        if d["statut"] == NON_PUBLIE:
            assert c not in INDEX["credits_etat_plf2026"]["territoires_lus"] and d["motif"], c
            continue
        assert not outremer.verifier_dpt({"total": d["total_general"], "missions": d["missions"]}), c
        for j in range(6):
            assert abs(sum(m["valeurs"][j] for m in d["missions"]) - d["total_general"][j]) <= len(d["missions"]), c
        codes = [p["code"] for m in d["missions"] for p in m["programmes"]]
        assert len(codes) == len(set(codes)), c


def test_verifier_dpt_refuse_une_lecture_fausse():
    bon = {"total": [30] * 6, "missions": [
        {"mission": "A", "valeurs": [10] * 6, "programmes": [{"code": "101", "libelle": "x", "valeurs": [10] * 6}]},
        {"mission": "B", "valeurs": [20] * 6, "programmes": [{"code": "102", "libelle": "y", "valeurs": [5] * 6},
                                                             {"code": "103", "libelle": "z", "valeurs": [15] * 6}]}]}
    assert outremer.verifier_dpt(bon) == []
    faux = json.loads(json.dumps(bon))
    faux["missions"][1]["programmes"][0]["valeurs"][2] = 5005  # groupe de chiffres mal rattaché
    assert any("lfi_2025_ae" in f for f in outremer.verifier_dpt(faux))
    vide = json.loads(json.dumps(bon))
    vide["missions"][0]["valeurs"][0] = None
    assert outremer.verifier_dpt(vide) and outremer.verifier_dpt(None) and outremer.verifier_dpt({"total": None})


def test_valeurs_dpt_par_bord_droit_de_colonne():
    bord = 498.0
    def mot(texte, x1):
        return {"text": texte, "x0": x1 - 4 * len(texte), "x1": x1}
    mots = []
    for i, groupes in enumerate([["3", "191", "414"], ["0"], ["12", "005"], ["7"], ["1", "000"], ["999"]]):
        droite = bord - outremer.DPT_DECALAGES[i]
        for k, g in enumerate(reversed(groupes)):
            mots.append(mot(g, droite - 13 * k))
    mots.sort(key=lambda w: w["x0"])
    assert outremer._valeurs_dpt(mots, bord) == [3191414, 0, 12005, 7, 1000, 999]
    assert outremer._valeurs_dpt([mot("12", bord - 244), mot("5", bord - 20)], bord) is None  # ne finit pas au bord
    assert outremer._valeurs_dpt([mot("7", bord)], bord) == [None, None, None, None, None, 7]  # vide = null


def test_ecarts_publies_et_recalculables():
    assert INDEX["ecarts"]
    for e in INDEX["ecarts"]:
        assert e["montant"] - e["autre_montant"] == e["ecart"]
        if e["autre_montant"]:
            assert abs(e["ecart_pct"] - e["ecart"] / e["autre_montant"] * 100) < 0.006
        f = FICHES[e["territoire"]]
        dgf = [c["eur"].get(e["annee"], {}).get("dgf_totale") for c in f["dotations_communes"].get("communes", {}).values()]
        dgf += [x["eur"].get(e["annee"], {}).get("dgf_totale")
                for x in f["dotations_intercommunalites"].get("epci", {}).values()]
        dgf.append(f["dotations_collectivite"].get("eur", {}).get(e["annee"], {}).get("dgf_totale"))
        assert sum(v for v in dgf if v is not None) == e["autre_montant"], e


# --- Nouvelle-Calédonie : francs CFP et euros ---------------------------------------------------------------------

def test_parite_fixe_et_devise_source():
    assert outremer.XPF_PAR_EUR == 119.33174 == INDEX["parite_xpf"]["xpf_par_eur"] == NC["parite"]["xpf_par_eur"]
    assert NC["devise_source"] == "XPF" and FICHES["988"]["budget_collectivite"]["devise_source"] == "XPF"
    assert outremer.xpf_en_eur(1000) == 8 and outremer.xpf_en_eur(119331.74) == 1000
    assert outremer.xpf_en_eur(None) is None and outremer.xpf_en_eur(0) == 0
    assert INDEX["parite_xpf"]["territoires_en_francs_cfp"] == ["986", "987", "988"]


def test_chaque_montant_caledonien_en_xpf_et_en_euros():
    def verifier(q, ou):
        assert len(q) == 4 and all(isinstance(v, int) for v in q), ou
        for xpf, eur in ((q[0], q[2]), (q[1], q[3])):
            assert eur == round(xpf / 119.33174), ou
    for an, lignes in NC["collectivite"]["chapitres"].items():
        for l in lignes:
            verifier(l[6:], (an, l[:4]))
    for an, budgets in NC["collectivite"]["totaux"].items():
        for b, sens in budgets.items():
            for s, sections in sens.items():
                for sec, v in sections.items():
                    verifier(v["total"], (an, b, s, sec))
                    verifier(v["hors_ordre_et_reports"], (an, b, s, sec))
    for sigle, e in NC["etablissements"]["etablissements"].items():
        for an, sens in e["annees"].items():
            for s, sections in sens.items():
                for sec, q in sections.items():
                    verifier(q, (sigle, an))
    for i in NC["impots"]["impots"]:
        assert len(i["montants_xpf"]) == len(i["montants_eur"]) == len(NC["impots"]["annees"])
        for xpf, eur in zip(i["montants_xpf"], i["montants_eur"]):
            assert (xpf is None and eur is None) or eur == round(xpf / 119.33174), i["libelle"]


def test_totaux_caledoniens_egaux_a_la_somme_des_chapitres():
    for an, lignes in NC["collectivite"]["chapitres"].items():
        acc = {}
        for b, s, sec, chap, lib, nature, bt, re_, _, _ in lignes:
            t = acc.setdefault((b, s, sec), [0, 0, 0, 0])
            t[0] += bt
            t[1] += re_
            if nature == "reel":
                t[2] += bt
                t[3] += re_
        for (b, s, sec), t in acc.items():
            v = NC["collectivite"]["totaux"][an][b][s][sec]
            assert abs(v["total"][0] - t[0]) <= len(lignes) and abs(v["total"][1] - t[1]) <= len(lignes), (an, b, s, sec)
            assert abs(v["hors_ordre_et_reports"][1] - t[3]) <= len(lignes), (an, b, s, sec)
    assert set(NC["budgets"]) == {"01", "02", "03"}
    assert NC["annees"][0] == "2012" and NC["exercice_en_cours"] == int(NC["annees"][-1])


def test_nature_des_chapitres():
    assert outremer.nature_chapitre("001", "SOLDE EXECUTION SECTION INVESTISSEMENT") == "report"
    assert outremer.nature_chapitre("946", "TRANSFERTS ENTRE LES SECTIONS") == "ordre"
    assert outremer.nature_chapitre("925", "OPERATIONS PATRIMONIALES") == "ordre"
    assert outremer.nature_chapitre("953", "VIREMENT A LA SECTION D'INVESTISSEMENT") == "ordre"
    assert outremer.nature_chapitre("932", "ENSEIGNEMENT") == "reel"


# --- confidentialité ----------------------------------------------------------------------------------------------

def test_aucun_chapitre_nominatif_ni_personne():
    """Chapitres individualisés (libellés au nom d'entreprises, parfois individuelles) agrégés sans libellé."""
    libelles = set()
    for lignes in NC["collectivite"]["chapitres"].values():
        for l in lignes:
            assert re.fullmatch(r"\d{3}", l[3]), l[:5]
            libelles.add(l[4])
    assert len(libelles) < 40
    texte = json.dumps(NC, ensure_ascii=False)
    for motif in (r"\bSARL\b", r"\bSAS\b", r"\bE\.I\b", r"\bEURL\b"):
        assert not re.search(motif, texte), motif
    assert sum(NC["collectivite"]["chapitres_individualises_agreges"].values()) > 0
    tout = json.dumps([FICHES, INDEX], ensure_ascii=False)
    assert not outremer_cles_interdites(json.loads(tout))


def outremer_cles_interdites(x) -> list:
    interdites = {"adresse", "courriel", "email", "telephone", "dirigeant", "responsable", "prenom", "nom_prenom"}
    if isinstance(x, dict):
        return [k for k in x if k in interdites] + [k for v in x.values() for k in outremer_cles_interdites(v)]
    if isinstance(x, list):
        return [k for v in x for k in outremer_cles_interdites(v)]
    return []


# --- sources, recherche préalable, lecture ------------------------------------------------------------------------

def test_sources_recherche_publique_et_catalogue():
    r = INDEX["recherche_publique"]
    assert r["trouvailles"] and all(t["verdict"] for t in r["trouvailles"])
    for t in r["trouvailles"]:
        if "github.com/" in t["url"] and t["url"] != "https://github.com/search":
            assert t.get("dernier_commit") and t.get("licence"), t["nom"]
    for s in INDEX["sources"].values():
        assert s["url"].startswith("https://") and s["licence"] and s["verdict"], s["titre"]
    assert INDEX["sources_inaccessibles"]
    cat = json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))
    entree = next(s for s in cat["sources"] if s["id"] == outremer.ID_CATALOGUE)
    assert entree["domaine"] == "outremer" and "ODbL" in entree["licence"]
    noms = {u["nom"] for u in entree["urls"]}
    assert {f"geo_{c}.json" for c in CODES} | {f"dotations_communes_{c}.csv" for c in CODES} <= noms
    assert {"nc_budget.csv", "nc_impots.csv", "dpt2026_outremer.pdf", "ccomptes_financement_etat_outremer.zip"} <= noms


def test_fonctions_de_lecture():
    assert outremer.num("") is None and outremer.num("-") is None and outremer.num("0") == 0.0
    assert outremer.num("1 234,5") == 1234.5 and outremer.num(None) is None
    assert outremer.nom_ofgl("HIENGHENE (988)") == "HIENGHENE"
    assert outremer.propre("SOLDE D''EXECUTION  DE LA SECTION") == "SOLDE D'EXECUTION DE LA SECTION"
    assert outremer.cle_nom("Polynésie-Française") == outremer.cle_nom("Polynésie française")
    assert outremer._ecart("975", "2024", "a", 10, "b", None, "x") is None
    e = outremer._ecart("975", "2024", "a", 110, "b", 100, "x")
    assert e["ecart"] == 10 and e["ecart_pct"] == 10.0


def test_fichiers_sous_cinq_mega_octets_avec_entete():
    for f in DOSSIER.glob("*.json"):
        assert f.stat().st_size < 5_000_000, f.name
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"], f.name
    assert sorted(p.name for p in DOSSIER.glob("*.json")) == sorted(
        [f"{c}.json" for c in CODES] + ["988_budget.json", "index.json"])
