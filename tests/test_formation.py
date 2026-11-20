"""Formation professionnelle (pipeline/formation.py) : contrat, confidentialité, neutralité, conservation des totaux.

Les tests sur site/data/formation tournent sans réseau ni entrepôt ; la reproductibilité demande l'entrepôt
(data/lake/formation), sautée sinon.
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
DATA = SITE / "formation"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import formation  # noqa: E402
import sirene  # noqa: E402
from test_neutralite import fautes, textes  # noqa: E402


def lire(nom: str) -> dict:
    return json.loads((DATA / nom).read_text(encoding="utf-8"))


INDEX = lire("index.json")
FICHIERS = sorted(DATA.glob("*.json"))


# --- Fonctions du module (sans entrepôt) -----------------------------------------------------------------------------

def test_valeurs_absentes_jamais_zero():
    for v in ("", "nc", "NC", "n.c.", "secret", None, "null"):
        assert formation.num(v) is None, v
    assert formation.num("0") == 0 and formation.num("12.5") == 12.5 and formation.entier("3.0") == 3
    d = {}
    formation._plus(d, "a", None)
    assert d == {"a": None}
    formation._plus(d, "a", 2.0)
    formation._plus(d, "a", None)
    assert d == {"a": 2.0}


def test_siren_et_nom_sirene():
    assert formation.siren_de("81129252300107") == "811292523"
    assert formation.siren_de("123") is None and formation.siren_de("") is None and formation.siren_de(None) is None
    assert formation.nom_sirene("AFTRAL (AFTRAL)") == "AFTRAL"
    assert formation.nom_sirene("ASSOCIATION X (AX)") == "ASSOCIATION X (AX)"


def test_statut_inconnu_refuse():
    assert formation._groupe("Clos - Réalisation Totale") == "realise"
    assert formation._groupe("Rejeté") == "annule"
    with pytest.raises(SystemExit):
        formation._groupe("Statut jamais vu")
    assert set(formation.STATUTS.values()) == set(formation.GROUPES)


def test_regroupement_des_petites_cellules():
    c = {"municipal": [900, 10, 5, 1], "regional": [2, 4, 4, 1], "autres": [1, 1, 1, 1], "departemental": [9, 3, 3, 1]}
    lots = formation.regrouper(c)
    assert all(x["valeurs"][0] >= formation.SEUIL_ELUS for x in lots)
    assert sum(x["valeurs"][0] for x in lots) == 912 and sum(x["valeurs"][1] for x in lots) == 18
    assert sorted(m for x in lots for m in x["mandats"]) == sorted(c)
    assert {"mandats": ["autres", "departemental", "regional"], "valeurs": [12, 8, 8, 3]} in lots
    seul = formation.regrouper({"municipal": [900, 1, 1, 1], "regional": [2, 4, 4, 1]})
    assert seul == [{"mandats": ["municipal", "regional"], "valeurs": [902, 5, 5, 2]}]


def test_requetes_sans_colonne_nominative():
    """Aucune requête ne demande au portail un nom de personne, un lieu de mandat ou une raison sociale saisie."""
    interdits = re.compile(r"\b(nom|prenom|genre|lieu_mandat|raison_sociale\w*|nom_of|intitule_formation)\b")
    for sid, s in formation.SOURCES.items():
        if sid.startswith("fiphfp"):
            continue  # noms de départements et de régions
        for cle in ("select", "group_by"):
            assert not interdits.search(s["params"].get(cle, "")), (sid, cle)
    assert "group_by" in formation.SOURCES["elus_of"]["params"]
    for sid in ("mcf_engagees_mois", "mcf_engagees_dep", "mcf_engagees_certif", "mcf_entrees_of", "elus_of"):
        assert "group_by" in formation.SOURCES[sid]["params"], sid  # jamais d'export ligne à ligne


# --- Contrat et règles communes --------------------------------------------------------------------------------------

def test_fichiers_presents_entete_et_taille():
    assert {f.name for f in FICHIERS} == {"index.json", "cpf_mois.json", "cpf_departements.json",
                                          "cpf_certifications.json", "cpf_organismes.json", "cpf_usagers.json",
                                          "elus.json", "fiphfp.json"}
    for f in FICHIERS:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and "Caisse des dépôts" in d["source"], f.name
        assert f.stat().st_size < 5_000_000, f.name
        assert d["collecte_le"] == INDEX["date_sources"], f.name
    for rel in INDEX["fichiers"].values():
        assert (SITE / rel).exists(), rel


def test_libelles_neutres():
    erreurs = []
    for f in FICHIERS:
        d = json.loads(f.read_text(encoding="utf-8"))
        for cle, t in textes(d):
            erreurs += [f"{f.name} [{cle}] {r} : {t[:100]}" for r in fautes(t)]
    for t in [INDEX["cpf"]["definition"], INDEX["cpf"]["regle"], INDEX["confidentialite"]["regle"],
              INDEX["recherche_publique"]["conclusion"]] + [l["lecture"] for l in INDEX["liens"]] \
            + list(INDEX["cpf"]["financeurs"].values()) + list(INDEX["cpf"]["statuts"].values()):
        erreurs += [f"index : {r} : {t[:100]}" for r in fautes(t)]
    assert not erreurs, "\n".join(erreurs[:20])


# --- Confidentialité --------------------------------------------------------------------------------------------------

def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


def test_aucune_cle_de_personne():
    interdites = {"prenom", "prénom", "genre", "lieu_mandat", "elu", "raison_sociale", "adresse", "courriel",
                  "telephone", "dirigeant", "responsable", "code_postal"}
    for f in FICHIERS:
        assert not interdites & set(_cles(json.loads(f.read_text(encoding="utf-8")))), f.name


@pytest.mark.parametrize("nom", ["cpf_organismes.json", "elus.json"])
def test_organismes_nommes_personnes_morales_seulement(nom):
    d = lire(nom)
    assert d["regle_personnes"]
    sirens = [o["siren"] for o in d["organismes"]]
    assert len(sirens) == len(set(sirens))
    for o in d["organismes"]:
        assert sirene.siren_valide(o["siren"]) and sirene.personne_morale(o["categorie_juridique"]), o["siren"]
        assert o["nom"].strip()


def test_elus_agregats_seulement():
    d = lire("elus.json")
    assert "aucun élu" in d["avertissement"] or "nom d'aucun élu" in d["avertissement"]
    for a, disp in d["par_mandat"].items():
        for lots in disp.values():
            for c in lots:
                assert c["valeurs"][0] >= formation.SEUIL_ELUS, (a, c)
    for o in d["organismes"]:
        assert o["cumul"][0] >= formation.SEUIL_ELUS and "annees" not in o
    # totaux conservés : cellules par mandat, organismes nommés + autres
    for a in d["annees"]:
        t = d["totaux"][a]
        for i in range(4):
            assert abs(sum(c["valeurs"][i] for lots in d["par_mandat"][a].values() for c in lots) - t[i]) <= 4, (a, i)
        assert sum(v[0] for v in d["factures"]["annees"][a].values()) == t[0]
    for i in range(4):
        tout = sum(d["totaux"][a][i] for a in d["annees"])
        somme = sum(o["cumul"][i] for o in d["organismes"]) + sum(v[i] for v in d["autres_organismes"]["annees"].values())
        assert abs(somme - tout) <= len(d["organismes"]) + 10, i


# --- Conservation des montants du CPF --------------------------------------------------------------------------------

def test_mois_somment_a_l_annee_et_financeurs_au_montant():
    mois = lire("cpf_mois.json")["mois"]
    for a, v in INDEX["cpf"]["annees"].items():
        ms = [x for k, x in mois.items() if k.startswith(a)]
        assert abs(sum(x["montant_eur"] for x in ms) - v["montant_eur"]) <= 12
        assert sum(x["dossiers"] for x in ms) == v["dossiers"]
        assert abs(sum(v["financeurs_eur"].values()) - v["montant_eur"]) <= v["montant_eur"] * 0.005, a
        retenu = sum(s["montant_eur"] for g, s in v["par_statut"].items() if g != "annule")
        assert abs(retenu - v["montant_eur"]) <= 3
        assert v["complete"] == (len(ms) == 12 and int(a) < int(INDEX["date_sources"][:4]))
    assert [a for a, v in INDEX["cpf"]["annees"].items() if not v["complete"]] == [max(INDEX["cpf"]["annees"])]


def test_departements_et_lieu_non_communique_somment_a_l_annee():
    d = lire("cpf_departements.json")
    for a, v in INDEX["cpf"]["annees"].items():
        lignes = list(d["departements"][a].values()) + [d["lieu_non_communique"][a]]
        assert abs(sum(x[1] for x in lignes) - v["montant_eur"]) <= len(lignes)
        assert sum(x[0] for x in lignes) == v["dossiers"]
        assert abs(sum(x[6] for x in lignes) - v["par_statut"]["annule"]["montant_eur"]) <= len(lignes)
        assert abs(sum(x[1] for x in d["modalites"]["annees"][a].values()) - v["montant_eur"]) <= 3
        assert "44" in d["departements"][a] and "2A" in d["departements"][a]


def test_certifications_somment_a_l_annee():
    d = lire("cpf_certifications.json")
    assert d["ordre"]["cles"] == ["-montant_cumule_eur", "referentiel", "code"]
    cumuls = [c["montant_cumule_eur"] for c in d["certifications"]]
    assert cumuls == sorted(cumuls, reverse=True)
    for a, v in INDEX["cpf"]["annees"].items():
        somme = sum(c["annees"].get(a, [0, 0])[1] for c in d["certifications"]) + d["autres_certifications"]["annees"][a][1]
        assert abs(somme - v["montant_eur"]) <= len(d["certifications"]) + 1, a
        assert abs(sum(x[a][1] for x in d["par_referentiel"].values()) - v["montant_eur"]) <= 3
    assert d["nombre_certifications"] == len(d["certifications"]) + d["autres_certifications"]["nombre"]


def test_usagers_dimensions_somment_au_total():
    d = lire("cpf_usagers.json")
    for a, v in d["annees"].items():
        for dim in ("region", "sexe", "age", "situation"):
            for i in range(4):
                assert abs(sum(x[i] for x in v[dim].values()) - v["total"][i]) <= len(v[dim]), (a, dim, i)


def test_organismes_estimation_approchee_et_totaux():
    d = lire("cpf_organismes.json")
    assert d["estimation"]["statut"] == "approché" and INDEX["cpf"]["organismes"]["estimation"] == "approché"
    assert "prix moyen" in d["estimation"]["methode"] and d["estimation"]["producteur"] == "Le billet découpé (calcul du site)"
    assert "pas un montant versé" in d["avertissement"]
    assert "montant_approche_eur" in d["colonnes"] and not any(c.endswith("montant_eur") for c in d["colonnes"])
    assert d["ordre"]["cles"] == ["-entrees_cumulees", "siren"]
    cles = [(-o["entrees_cumulees"], o["siren"]) for o in d["organismes"]]
    assert cles == sorted(cles) and len(cles) <= formation.NB_ORGANISMES
    for a in d["annees"]:
        t = d["totaux"][a]
        for i, cle in enumerate(d["colonnes"]):
            somme = sum(o["annees"].get(a, [0] * 4)[i] for o in d["organismes"]) \
                + sum((g["annees"].get(a) or [0] * 5)[i] or 0 for g in d["agreges"].values())
            assert abs(somme - t[cle]) <= len(d["organismes"]) + 10, (a, cle)
        assert sum(t["entrees_par_niveau_de_prix"].values()) == t["entrees"]
        c = t["controle_estimation"]
        assert abs(t["montant_approche_eur"] - c["montant_engage_rncp_rs_eur"] - c["ecart_eur"]) <= 1
    assert sum(g["organismes"] or 0 for g in d["agreges"].values()) == sum(
        INDEX["confidentialite"]["organismes_agreges"][k] or 0 for k in d["agreges"])


# --- FIPHFP -----------------------------------------------------------------------------------------------------------

def test_fiphfp_absences_gardees_et_totaux():
    d = lire("fiphfp.json")
    a = d["aides"]
    assert any(v is None for an in a["departements"].values() for x in an.values() for v in x)  # null, jamais 0 forcé
    for an in a["annees"]:
        t = a["totaux"][an]
        for i, col in enumerate(a["colonnes"]):
            vals = [x[i] for x in a["departements"][an].values() if x[i] is not None]
            assert (t[col] is None and not vals) or abs(sum(vals) - t[col]) <= len(vals) + 1, (an, col)
        assert abs(sum(v or 0 for k, v in t.items() if k != "total") - t["total"]) <= 5
        assert "2019" in a["annees"] and len(a["departements"]["2019"]) >= 95   # codes retrouvés par le nom
    c = d["conventions"]
    for an in c["annees"]:
        for i, col in enumerate(c["colonnes"]):
            vals = [x[i] for x in c["regions"][an].values() if x[i] is not None]
            assert abs(sum(vals) - (c["totaux"][an][col] or 0)) <= len(vals) + 1
    assert "ne sont pas additionnées" in d["avertissement"]


# --- Liens, écarts, sources -------------------------------------------------------------------------------------------

def test_liens_vers_les_financeurs():
    vues = {l["vue"]: l for l in INDEX["liens"]}
    assert set(vues) == {"operateurs", "arbre_etat"}
    for l in INDEX["liens"]:
        assert (SITE / l["fichier"]).exists()
        assert "jamais additionné" in l["lecture"] or "ne lui sont pas additionnées" in l["lecture"]
    op = json.loads((SITE / vues["operateurs"]["fichier"]).read_text(encoding="utf-8"))
    fc = next(o for o in op["operateurs"] if o["id"] == "francecompetences")
    assert fc["programme_chef_de_file"] == "103" == vues["arbre_etat"]["programme"]
    arbre = json.loads((SITE / vues["arbre_etat"]["fichier"]).read_text(encoding="utf-8"))
    assert arbre["id"] == vues["arbre_etat"]["id"] and arbre["md"] == vues["arbre_etat"]["md"]
    for an, v in vues["operateurs"]["annees"].items():
        assert v["financement_etat_cp_eur"] == fc["annees"][an]["financement_etat_total_cp_eur"]


def test_ecarts_publies_et_recalculables():
    assert len(INDEX["ecarts"]) >= 4
    for e in INDEX["ecarts"]:
        assert e["montant"] == INDEX["cpf"]["annees"][str(e["annee"])]["montant_eur"]
        assert abs(e["montant"] - e["autre_montant"] - e["ecart"]) <= 1
        assert abs(e["ecart_pct"] - (e["montant"] - e["autre_montant"]) / e["autre_montant"] * 100) < 0.06
        assert abs(formation._nombre_fr(e["autre_publie"]) - e["autre_montant"]) < 1
        assert "aucun n'est retenu" in e["lecture_ecart"]
    v = INDEX["verification_documents"]
    assert v is None or v["valeurs"] == v["retrouvees"] == 8


def test_sources_et_recherche_publique():
    assert set(INDEX["sources"]) == set(formation.SOURCES)
    assert any("DARES" in s["source"] for s in INDEX["sources_inaccessibles"])
    verdicts = {t["verdict"].split(" (")[0] for t in INDEX["recherche_publique"]["trouvailles"]}
    assert verdicts == {"réutilisable tel quel", "à adapter", "inspiration seulement"}
    for t in INDEX["recherche_publique"]["trouvailles"]:
        assert t["licence"] and t["mise_a_jour"] and t["url"].startswith("https://")


# --- Reproductibilité (entrepôt requis) -------------------------------------------------------------------------------

@pytest.mark.skipif(not all((formation.BRUT / s["fichier"]).exists() for s in formation.SOURCES.values()),
                    reason="entrepôt data/lake/formation absent : reproductibilité non vérifiable ici")
def test_produire_deux_fois_donne_les_memes_octets(tmp_path):
    empreintes = []
    for graine in ("1", "2"):
        sortie = tmp_path / graine
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "formation.py"), "produire", "--sortie", str(sortie)],
                       check=True, capture_output=True, env={**os.environ, "PYTHONHASHSEED": graine})
        empreintes.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sortie.glob("*.json"))})
    assert empreintes[0] == empreintes[1] and len(empreintes[0]) == 8
    publie = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in FICHIERS}
    assert empreintes[0] == publie, "site/data/formation ne correspond pas à l'entrepôt : relancer produire"
