"""Pouvoirs publics (pipeline/pouvoirs_publics.py) : contrat, neutralité, confidentialité, cohérence des totaux.

Les tests sur site/data/pouvoirs_publics tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/pouvoirs_publics/), sautée sinon.
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
DATA = ROOT / "site" / "data" / "pouvoirs_publics"
LAKE = ROOT / "data" / "lake" / "pouvoirs_publics"
sys.path.insert(0, str(ROOT / "tests"))
from test_neutralite import fautes, textes  # noqa: E402

FICHIERS = ["index.json", "dotations.json", "budgets.json", "indemnites.json"]
# Jugements propres au sujet, en plus du lexique partagé.
JUGEMENTS = re.compile(r"(?<!\w)(?:privil[eè]g\w*|train de vie|dispendieu\w*|fastueu\w*|largesses?|"
                       r"exemplaire\w*|sobri[ée]t[ée]|rigoureu\w*|maîtris\w*)(?!\w)", re.I)
CIVILITE = re.compile(r"(?<!\w)(?:M\.|Mme|Mmes|MM\.|Monsieur|Madame)\s+[A-ZÉÈ]")


def _lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dotations():
    return _lire("dotations.json")


@pytest.fixture(scope="module")
def budgets():
    return _lire("budgets.json")


@pytest.fixture(scope="module")
def indemnites():
    return _lire("indemnites.json")


@pytest.mark.parametrize("nom", FICHIERS)
def test_entete_et_taille(nom):
    p = DATA / nom
    assert p.stat().st_size < 1_000_000
    d = _lire(nom)
    assert d["millesime"] and len(d["source"]) >= 20
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date_sources"])


@pytest.mark.parametrize("nom", FICHIERS)
def test_neutralite_et_confidentialite(nom):
    erreurs = []
    for cle, t in textes(_lire(nom)):
        erreurs += [f"[{cle}] {r} : {t[:100]}" for r in fautes(t)]
        if JUGEMENTS.search(t):
            erreurs.append(f"[{cle}] jugement : {t[:100]}")
        if "—" in t:
            erreurs.append(f"[{cle}] tiret long : {t[:100]}")
        if CIVILITE.search(t):
            erreurs.append(f"[{cle}] personne nommée : {t[:100]}")
    assert not erreurs, "\n".join(erreurs[:20])


def test_aucune_cle_personnelle():
    interdites = {"nom", "prenom", "prénom", "adresse", "courriel", "telephone", "dirigeant", "titulaire"}

    def cles(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from cles(v)
        elif isinstance(x, list):
            for v in x:
                yield from cles(v)
    for nom in FICHIERS:
        d = _lire(nom)
        d.pop("recherche_publique", None)    # « nom » d'un jeu ou d'un dépôt, pas d'une personne
        assert not interdites & set(cles(d)), nom


def test_index_fichiers_et_sources():
    idx = _lire("index.json")
    assert {f["fichier"] for f in idx["fichiers"]} == {f"pouvoirs_publics/{n}" for n in FICHIERS if n != "index.json"}
    for f in idx["fichiers"]:
        assert (DATA.parent / f["fichier"]).stat().st_size == f["octets"]
    assert all(s["url"] and s["url"].startswith("https://") for s in idx["sources"])
    assert idx["sources_inaccessibles"] and all(s["motif"] and s["consequence"] for s in idx["sources_inaccessibles"])
    verdicts = {t["verdict"] for t in idx["recherche_publique"]["trouvailles"]}
    assert verdicts <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}


def test_series_continues_et_absences_a_null(dotations):
    codes = [p["programme"] for p in dotations["programmes"]]
    assert {"501", "511", "521", "531", "533", "541"} <= set(codes)
    for p in dotations["programmes"]:
        annees = [l["annee"] for l in p["annees"]]
        assert annees == list(range(annees[0], annees[-1] + 1)), p["programme"]
        for l in p["annees"]:
            for g in ("lfi", "plf", "execute"):
                assert (l[g] is None) == (l[f"source_{g}"] is None), (p["programme"], l["annee"], g)
                assert l[g] is None or l[g] >= 0
        lfi = {l["annee"]: l["lfi"] for l in p["annees"]}
        assert lfi[2016] is None, "aucun document lu pour 2016 : null, jamais 0"
    absentes = {(v["programme"], v["annee"], v["grandeur"]) for v in dotations["valeurs_absentes"]}
    assert ("511", 2016, "lfi") in absentes


def test_totaux_publies_egaux_a_la_somme_des_programmes(dotations):
    for t in dotations["totaux_publies"]:
        lignes = [next(l for l in p["annees"] if l["annee"] == t["annee"]) for p in dotations["programmes"]]
        if all(l[f"source_{t['grandeur']}"] == t["source"] for l in lignes):
            assert sum(l[t["grandeur"]] for l in lignes) == t["montant_eur"], t


def test_actions_retombent_sur_le_programme(dotations):
    for p in dotations["programmes"]:
        if not p["actions"]:
            continue
        for l in p["annees"]:
            for g in ("lfi", "plf"):
                vals = [next((x[g] for x in a["annees"] if x["annee"] == l["annee"]), None) for a in p["actions"]]
                if l[g] is not None and None not in vals and l[f"source_{g}"].startswith("pouvoirs_publics_pap"):
                    assert sum(vals) == l[g], (p["programme"], l["annee"], g)


def test_ecarts_montres_pas_tranches(dotations, budgets):
    for e in dotations["ecarts"]:
        assert e["ecart_eur"] == e["autre_montant_eur"] - e["montant_eur"] and e["source"] != e["autre_source"]
    for e in budgets["assemblee_nationale"]["ecarts_entre_annexes"]:
        assert e["ecart_eur"] == e["autre_montant_eur"] - e["montant_eur"] and e["document"] != e["autre_document"]


def test_syntheses_assemblee_coherentes(budgets):
    for s in budgets["assemblee_nationale"]["syntheses"]:
        t = {l["code"]: l["valeurs_eur"] for l in s["lignes"]}
        for c in (x["cle"] for x in s["colonnes"]):
            v = {k: t[k][c] for k in t}
            assert abs(sum(v[k] for k in ("60", "61-62", "63", "64", "65", "67-69")) - v["A"]) <= 2
            assert abs(v["A"] + v["B"] - v["C"]) <= 2
            assert abs(v["D"] + v["E"] - v["C"] - v["F"]) <= 2


def test_dotation_assemblee_identique_dans_les_deux_vues(budgets, dotations):
    """La dotation de l'État dans le budget de l'Assemblée et le crédit voté du programme 511 : même montant."""
    lfi = {l["annee"]: l["lfi"] for l in next(p for p in dotations["programmes"] if p["programme"] == "511")["annees"]}
    for s in budgets["assemblee_nationale"]["syntheses"]:
        e = next(l for l in s["lignes"] if l["code"] == "E")["valeurs_eur"]
        for c in s["colonnes"]:
            if c["nature"] == "réalisé" and lfi.get(c["annee"]) is not None:
                assert e[c["cle"]] == lfi[c["annee"]], c


def test_autres_institutions(budgets):
    se = budgets["senat"]["montants_2025"]
    assert round(se["solde_publie_meur"] - se["solde_recalcule_meur"], 3) == se["ecart_solde_meur"]
    cc = budgets["conseil_constitutionnel"]
    assert sum(p["montant_eur"] for p in cc["par_nature"]) == cc["total_eur"]
    for c in budgets["cour_justice_republique"]["controles"].values():
        assert c["total_publie_eur"] - c["somme_des_lignes_lisibles_eur"] == c["ecart_eur"]
    pr = budgets["presidence"]["equilibre"]
    v = {l["poste"]: l["valeurs_meur"] for l in pr["lignes"]}
    for c in (x["cle"] for x in pr["colonnes"]):
        assert abs(v["Dotation de l'État"][c] + v["Produits propres"][c] - v["Dépenses"][c] - v["Solde"][c]) <= 0.06


def test_baremes_indemnites(indemnites):
    lignes = indemnites["lignes"]
    for inst in ("Assemblée nationale", "Sénat"):
        par = {l["composante"]: l["montant_mensuel_eur"] for l in lignes
               if l["institution"] == inst and l["fonction"] in ("Député", "Sénateur")}
        base, res, fon = (par["indemnité parlementaire de base"], par["indemnité de résidence (3 %)"],
                          par["indemnité de fonction (25 %)"])
        assert abs(res - 0.03 * base) <= 0.01 and abs(fon - 0.25 * (base + res)) <= 0.01
        assert abs(base + res + fon - par["total brut mensuel"]) <= 0.02
    for l in lignes:
        if l["montant_mensuel_eur"] is None:
            assert l["mention"] and l["statut"] == "non publié dans les sources lues"
        if l["statut"] == "calculé":
            b = l["entrees"]["indemnite_parlementaire_de_base_eur"]
            t = 2 * b
            assert l["montant_mensuel_eur"] == round((t * 1.03) * 1.25 * 1.05, 2) and l["formule"] and l["limite"]


@pytest.mark.skipif(not (LAKE / "pouvoirs_publics_pap_2026.pdf").exists(),
                    reason="entrepôt data/lake/pouvoirs_publics absent : reproductibilité non vérifiable ici")
def test_reproductible(tmp_path):
    empreintes = []
    for graine, dossier in (("1", tmp_path / "a"), ("2", tmp_path / "b")):
        env = {**os.environ, "PYTHONHASHSEED": graine}
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "pouvoirs_publics.py"), "produire", "--sortie",
                        str(dossier)], check=True, env=env, cwd=ROOT)
        empreintes.append({n: hashlib.sha256((dossier / n).read_bytes()).hexdigest() for n in FICHIERS})
    assert empreintes[0] == empreintes[1]
    assert empreintes[0] == {n: hashlib.sha256((DATA / n).read_bytes()).hexdigest() for n in FICHIERS}
