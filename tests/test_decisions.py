"""Tests sans réseau des décisions (pipeline/decisions.py) : extraction sur échantillons, contrôle JO / PLRG,
absence de données personnelles hors noms d'élus."""
import io
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import decisions  # noqa: E402

DEC = ROOT / "site" / "data" / "decisions"
FICHIERS = sorted(DEC.glob("*.json")) if DEC.exists() else []
avec_sortie = pytest.mark.skipif(not FICHIERS, reason="site/data/decisions absent")

NOMEN = {"par_mission": {"justice": {"justice judiciaire": "166", "administration penitentiaire": "107"}},
         "par_lib": {"justice judiciaire": {"166"}, "administration penitentiaire": {"107"},
                     "sport": {"219"}}, "libelles": {}}

# --- Extraction programme / montant -----------------------------------------------------------------------------------

DIS_SENAT = """<body><p>Modifier ainsi les cr&#233;dits des programmes&#160;:</p><table>
<tr><td><b>Programmes</b></td><td colspan="2">Autorisations d&#8217;engagement</td><td colspan="2">Cr&#233;dits de paiement</td></tr>
<tr><td>&#160;</td><td>+</td><td>-</td><td>+</td><td>-</td></tr>
<tr><td>Justice judiciaire dont titre 2</td><td>1&#160;000&#160;000</td><td></td><td>500&#160;000</td><td></td></tr>
<tr><td>Administration p&#233;nitentiaire</td><td></td><td>1&#160;000&#160;000</td><td></td><td>500 000</td></tr>
<tr><td>TOTAL</td><td>1 000 000</td><td>1 000 000</td><td>500 000</td><td>500 000</td></tr>
<tr><td>SOLDE</td><td colspan="2">0</td><td colspan="2">0</td></tr></table></body>"""


def test_tableau_senat():
    l = decisions.lignes_tableau_credits(DIS_SENAT)
    assert [(x["libelle"], x["ae"], x["cp"]) for x in l] == [
        ("Justice judiciaire", 1_000_000, 500_000), ("Administration pénitentiaire", -1_000_000, -500_000)]
    assert decisions.resoudre(NOMEN, l[0]["libelle"], None) == ("166", "exact")
    assert decisions.resoudre(NOMEN, "Administration penitentiaire", "Justice") == ("107", "exact")
    assert decisions.resoudre(NOMEN, "Programme inconnu", "Justice")[0] is None


def test_cellule_avec_dont_titre2():
    dis = DIS_SENAT.replace("<td>1&#160;000&#160;000</td>", "<td><p>1 000 000</p><p>800&#160;000</p></td>", 1)
    assert decisions.lignes_tableau_credits(dis)[0]["ae"] == 1_000_000


def test_ligne_an_plf_et_plfr():
    assert decisions.ae_cp({"creditPaiement": "-3000000"}, "creditPaiement") == -3_000_000
    p = {"creditPaiementSupplementaire": "1000", "creditPaiementAnnule": "-89677479"}
    assert decisions.ae_cp(p, "creditPaiement") == 1000 - 89_677_479


ARTICLE_JORF = """<p>ANNEXE<br/>TABLEAU 1</p><table border="1">
<tr><th>INTITULÉS DE LA MISSION et du programme</th><th>NUMÉRO du programme</th>
<th>AUTORISATIONS d'engagement annulées</th><th>CRÉDITS de paiement annulés</th></tr>
<tr><td>Défense</td><td/><td/><td>1 575 000 000</td></tr>
<tr><td>Préparation et emploi des forces</td><td>178</td><td/><td>1 144 000 000</td></tr>
<tr><td>Dont titre 2</td><td/><td>5,00</td><td>5,00</td></tr>
<tr><td>Totaux</td><td/><td/><td>1 575 000 000</td></tr></table>
<p>TABLEAU 2</p><table border="1">
<tr><th>INTITULÉS</th><th>NUMÉRO du programme</th><th>AUTORISATIONS d'engagement ouvertes</th>
<th>CRÉDITS de paiement ouverts</th></tr>
<tr><td>Préparation et emploi des forces</td><td>178</td><td>10,50</td><td>1 144 000 000</td></tr></table>"""


def test_tableaux_jorf_signes():
    lignes, perdues = decisions.lignes_tableaux_jorf(ARTICLE_JORF, "report")
    assert lignes == [{"programme": "178", "ae": 0.0, "cp": -1_144_000_000.0},
                      {"programme": "178", "ae": 10.5, "cp": 1_144_000_000.0}]
    assert perdues == 1  # ligne de mission (sous-total)


def test_type_mouvement():
    assert decisions.type_mouvement("Décret n° 2024-124 du 21 février 2024 portant annulation de crédits")[0] == \
        "annulation"
    assert decisions.type_mouvement("Décret du 3 avril 2025 portant ouverture et annulation de crédits à titre "
                                    "d'avance")[0] == "decret_avance"
    assert decisions.type_mouvement("Arrêté du 17 janvier 2024 portant report de crédits")[0] == "report"
    assert decisions.type_mouvement("Décret portant virement de crédits")[1] == "mouvements_reglementaires"
    assert decisions.type_mouvement("Arrêté portant délégation de signature")[0] is None


def test_copy_postgresql():
    dump = io.StringIO("SET x;\nCOPY amd (id, num, dis) FROM stdin;\n1\tII-1\ta\\tb\n2\t3\t\\N\n\\.\n"
                       "COPY autre (id) FROM stdin;\n9\n\\.\n")
    d = decisions.lire_copy(dump, {"amd"})
    assert d["amd"] == [{"id": "1", "num": "II-1", "dis": "a\tb"}, {"id": "2", "num": "3", "dis": None}]


# --- Somme des mouvements vs PLRG (tolérance publiée) --------------------------------------------------------------


def test_coherence_sur_echantillon():
    mvts = [{"annee_gestion": 2024, "type": "virement", "lignes": [{"programme": "129", "cp": 35.0},
                                                                    {"programme": "552", "cp": -35.0}]},
            {"annee_gestion": 2024, "type": "report", "lignes": [{"programme": "129", "cp": -7.0},
                                                                  {"programme": "129", "cp": 7.0}]}]
    plrg = {2024: {"129": {"mouvements_reglementaires": 35.0, "reports_entrants": 7.0, "fonds_de_concours": 0.0},
                   "552": {"mouvements_reglementaires": -30.0, "reports_entrants": 0.0, "fonds_de_concours": 0.0}}}
    c = decisions.coherence(mvts, plrg)["2024"]
    assert c["reports_entrants"]["ecart_absolu_cp"] == 0 and c["reports_entrants"]["conforme"]
    mr = c["mouvements_reglementaires"]
    assert mr["ecart_absolu_cp"] == 5.0 and mr["ecart_pct"] == round(100 * 5 / 65, 3)
    assert mr["conforme"] is (mr["ecart_pct"] <= decisions.TOLERANCE_PCT)
    assert mr["programmes_conformes"] == 2  # 5 € <= tolérance par programme


@avec_sortie
def test_coherence_publiee_recalculable():
    c = json.loads((DEC / "coherence_plrg.json").read_text(encoding="utf-8"))
    tol = c["tolerance"]["pct_par_annee"]
    for a, r in c["annees"].items():
        for col, v in r.items():
            if v["ecart_pct"] is not None:
                assert v["conforme"] is (v["ecart_pct"] <= tol), (a, col)
                assert abs(sum(abs(e["ecart_cp"]) for e in v["ecarts"]) - v["ecart_absolu_cp"]) <= \
                    c["tolerance"]["eur_par_programme"] * v["programmes"] + 1, (a, col)


# --- Données personnelles -----------------------------------------------------------------------------------------

INTERDIT = re.compile(r"naiss|dateNais|villeNais|adresse|mail|telephone|profession|prenom|uri_hatvp", re.I)
TYPES_AUTEURS = {"député", "sénateur", "gouvernement", "commission", "rapporteur", "autre"}


def _cles(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _cles(v)
    elif isinstance(o, list):
        for v in o:
            yield from _cles(v)


def _auteurs(o):
    if isinstance(o, dict):
        if "auteur" in o and isinstance(o["auteur"], dict):
            yield o["auteur"]
        for v in o.values():
            yield from _auteurs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _auteurs(v)


@avec_sortie
def test_aucun_champ_personnel_hors_nom_elu():
    for f in FICHIERS:
        d = json.loads(f.read_text(encoding="utf-8"))
        for k in _cles(d):
            assert not INTERDIT.search(k), (f.name, k)
        for a in _auteurs(d):
            assert set(a) <= {"type", "nom", "groupe", "masque"}, (f.name, a)
            assert a["type"] in TYPES_AUTEURS or a["type"].startswith(("rapporteur", "président")), (f.name, a)
            if a["type"] == "gouvernement":
                assert a["nom"] == "Gouvernement"


@avec_sortie
def test_fichiers_portent_millesime_source_et_taille():
    for f in FICHIERS:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d.get("millesime") and d.get("source"), f.name
        assert f.stat().st_size < 5_000_000, f.name
