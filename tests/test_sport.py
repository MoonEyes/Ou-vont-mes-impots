"""Sport (pipeline/sport.py) : cohérence des fichiers publiés et fonctions de lecture, sans réseau."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "sport"
sys.path.insert(0, str(ROOT / "pipeline"))
import sirene  # noqa: E402
import sport  # noqa: E402

PUBLIE, NON_PUBLIE = "publié", "non publié en données ouvertes"


# --- fonctions de lecture (sans fichier) ----------------------------------------------------------------------------

def test_tableau5_recolle_les_libelles_sur_deux_lignes_et_controle_les_totaux():
    lignes = [
        "texte avant", sport.TABLEAU5, "Montant évalué au 30 juin", "En M€", "2025",
        "Haute performance 80,3",
        "Subventions à l’association « Ambition olympique et", "27,8", "paralympique et au GIP « Paris 2024 »",
        "Sécurité 1 440,3",
        "Total dépenses d’organisation 1 548,4",
        "Baignade 330,9",
        "Financement (hors ouvrages) et réserves", "209,4", "de la Solideo",
        "Total dépenses d’infrastructures 540,3",
        "Source : Cour des comptes",
    ]
    postes, totaux, fautes = sport.tableau5(lignes)
    assert fautes == []
    assert totaux == {"organisation": 1548.4, "infrastructures": 540.3}
    assert [p["poste"] for p in postes] == [
        "Haute performance", "Subventions à l’association « Ambition olympique et paralympique et au GIP « Paris 2024 »",
        "Sécurité", "Baignade", "Financement (hors ouvrages) et réserves de la Solideo"]
    assert postes[2] == {"volet": "organisation", "poste": "Sécurité", "montant_meur": 1440.3}
    assert postes[4]["volet"] == "infrastructures"


def test_tableau5_refuse_un_tableau_dont_la_somme_ne_tombe_pas():
    lignes = [sport.TABLEAU5, "A 10,0", "B 5,0", "Total dépenses d’organisation 16,0", "C 1,0",
              "Total dépenses d’infrastructures 1,0", "Source : Cour des comptes"]
    _, _, fautes = sport.tableau5(lignes)
    assert len(fautes) == 1 and "organisation" in fautes[0]
    assert sport.tableau5(["rien"])[2] == ["tableau n° 5 introuvable dans le rapport"]


def test_montants_absents_jamais_zero():
    assert sport.montant(None) is None and sport.montant("nc") is None and sport.montant("") is None
    assert sport.montant(0) == 0.0 and sport.montant("1 234,5") == 1234.5


def test_codes_departement_et_federations():
    assert sport.code_departement(3) == "03" and sport.code_departement("2A") == "2A"
    assert sport.code_departement(985) == "976" and sport.code_departement(None) is None
    assert sport.est_federation("FEDERATION FRANCAISE DE SKI")
    assert sport.est_federation("FEDE FR JUDO JUJITSU KENDO DISC ASSOCIE")
    assert sport.est_federation("COMITE REGIO ILE FRANCE FEDER FR GYMNAST")
    assert not sport.est_federation("UNION NATIONALE DU SPORT SCOLAIRE")
    assert not sport.est_federation("FEDERAL CLUB") and not sport.est_federation("")


def test_colonnes_nominatives_du_cnds_jamais_lues():
    """Les colonnes de noms et d'adresses du CNDS ne sont jamais demandées au lecteur xlsx."""
    code = (ROOT / "pipeline" / "sport.py").read_text(encoding="utf-8")
    appels = re.findall(r"lire_xlsx\(CNDS\[\"\w+\"\], \(([^)]*)\)\)", code)
    assert len(appels) == 3
    for a in appels:
        for interdit in ("Beneficiaire", "Siege", "CP", "Porteur_projet", "Projet", "Commune"):
            assert f'"{interdit}"' not in a, (interdit, a)


# --- fichiers publiés ---------------------------------------------------------------------------------------------

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/sport absent : lancer `python pipeline/sport.py produire`", allow_module_level=True)


def charger(nom):
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


INDEX = charger("index.json")
BUDGET = charger("budget.json")
FED = charger("federations.json")
CNDS = charger("cnds_2015.json")
JOP = charger("jop.json")


def test_fichiers_legers_avec_millesime_et_source():
    for f in sorted(DOSSIER.glob("*.json")):
        assert f.stat().st_size < 1_000_000, f
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"], f
    assert sorted(p.name for p in DOSSIER.glob("*.json")) == sorted(
        [Path(v).name for v in INDEX["fichiers"].values()] + ["index.json"])


def test_blocs_et_statuts():
    assert set(INDEX["statuts"]) == {PUBLIE, NON_PUBLIE}
    for nom, b in INDEX["blocs"].items():
        if b["statut"] == NON_PUBLIE:
            assert set(b) == {"statut", "motif"} and len(b["motif"]) > 30, nom
        else:
            assert b["source"] in INDEX["sources"] and (SITE / b["fichier"]).exists(), nom
    assert INDEX["blocs"]["agence_nationale_du_sport_subventions"]["statut"] == NON_PUBLIE
    assert any("agencedusport.fr" in s["source"] for s in INDEX["sources_inaccessibles"])
    assert {t["verdict"].split(" (")[0] for t in INDEX["recherche_publique"]["trouvailles"]} <= {
        "réutilisable tel quel", "à adapter", "inspiration", "aucun dépôt trouvé",
        "à adapter (rapport) ; inspiration seulement"}


def test_budget_repris_tel_quel_des_realisations():
    for p in ("219", "350"):
        r = json.loads((SITE / "realisations" / f"{p}.json").read_text(encoding="utf-8"))["prevu_depense"]["annees"]
        b = BUDGET["programmes"][p]["annees"]
        assert [a["annee"] for a in b] == [a["annee"] for a in r]
        for x, y in zip(b, r):
            assert x["depense_constatee_eur"] == y["depense_constatee_eur"], (p, x["annee"])
            assert x["vote_lfi_eur"] == y["vote_lfi_eur"], (p, x["annee"])
    ops = json.loads((SITE / "operateurs" / "operateurs.json").read_text(encoding="utf-8"))
    ans = next(o for o in ops["operateurs"] if o["id"] == "ans")
    a = BUDGET["agence_nationale_du_sport"]
    assert a["siren"] == ans["siren"] and [str(x["annee"]) for x in a["annees"]] == sorted(ans["annees"])
    for x in a["annees"]:
        assert x["financement_etat_total_cp_eur"] == ans["annees"][str(x["annee"])].get("financement_etat_total_cp_eur")


def test_federations_personnes_morales_nommees_et_ordonnees():
    assert FED["federations"]
    for f in FED["federations"]:
        assert sirene.personne_morale(f["categorie_juridique"]) and sirene.siren_valide(f["siren"]), f
        assert sport.est_federation(f["denomination"]), f
        assert len(f["montants_eur"]) == len(FED["annees_plf"])
    cles = [(-f["total_eur"], f["siren"]) for f in FED["federations"]]
    assert cles == sorted(cles)
    for k, pa in enumerate(FED["par_annee"]):
        if pa["statut"] != "publie":
            assert pa["federations_eur"] is None
            continue
        s = sum(f["montants_eur"][k] or 0 for f in FED["federations"])
        assert abs(s - pa["federations_eur"]) < 1, pa


def test_cnds_sommes_coherentes_et_aucun_beneficiaire():
    pt = CNDS["part_territoriale"]
    t = pt["total_eur"]
    for cle in ("par_federation", "par_service", "par_region", "par_objectif"):
        assert abs(sum(e["montant_eur"] for e in pt[cle]) - t) < 1, cle
    assert pt["services_non_rattaches"] == []
    for r in pt["par_region"]:
        assert abs(r["services_regionaux_eur"] + r["services_departementaux_eur"] - r["montant_eur"]) < 1, r
    par_fed = {f["code"]: f["montant_eur"] for f in pt["par_federation"]}
    for code, regs in pt["federation_par_region"]["valeurs"].items():
        assert abs(sum(regs.values()) - par_fed[code]) < 1, code
    pe = CNDS["part_equipement"]
    assert abs(sum(d["montant_accorde_eur"] for d in pe["par_departement"]) - pe["total_accorde_eur"]) < 1
    assert abs(sum(d["montant_accorde_eur"] for d in pe["par_region"]) - pe["total_accorde_eur"]) < 1
    pn = CNDS["part_nationale"]
    assert abs(sum(d["montant_eur"] for d in pn["par_type"]) - pn["total_eur"]) < 1
    def cles(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k.lower()
                yield from cles(v)
        elif isinstance(x, list):
            for v in x:
                yield from cles(v)
    interdits = {"beneficiaire", "beneficiaires", "porteur_projet", "projet", "siege", "cp", "commune", "adresse",
                 "nom_beneficiaire", "siren"}
    assert not set(cles(CNDS)) & interdits


def test_cnds_regions_actuelles():
    codes = {r["code"] for r in CNDS["part_territoriale"]["par_region"]}
    assert {"11", "84", "93", "44", "04", "975", "988"} <= codes
    for s in CNDS["part_territoriale"]["par_service"]:
        assert s["niveau"] in ("régional", "départemental", "collectivité d'outre-mer"), s
        assert (s["departement"] is not None) == (s["niveau"] == "départemental"), s


def test_jop_cour_des_comptes_avec_perimetre_methode_et_controle():
    assert JOP["producteur"] == "Cour des comptes"
    assert len(JOP["perimetre"]) > 100 and len(JOP["methode"]) > 100
    if JOP["statut"] != PUBLIE:
        assert JOP["motif"] and "postes" not in JOP
        return
    assert JOP["fautes_controle"] == [] and JOP["citations_non_retrouvees"] == []
    for volet, total in JOP["totaux_meur"].items():
        s = sum(p["montant_meur"] for p in JOP["postes"] if p["volet"] == volet)
        assert abs(s - total) <= 0.2, volet
    assert JOP["totaux_meur"] == {"organisation": 3019.2, "infrastructures": 3631.4}
    assert len(JOP["par_acteur"]["acteurs"]) == 3
    assert JOP["autres_montants"]["depenses_nettes_organisation_meur"]["montant_meur"] == 2730.0
    assert JOP["estimation_anterieure"]["organisation_meur"] == 2770.0
    assert JOP["programme_350"]["fichier"] == "realisations/350.json"
    assert "jamais additionnée" in JOP["programme_350"]["lecture"]


def test_chiffres_cles_coherents():
    c = INDEX["chiffres_cles"]
    assert c["cnds_2015_part_territoriale_eur"] == CNDS["part_territoriale"]["total_eur"]
    assert c["jop_organisation_meur"] == JOP.get("totaux_meur", {}).get("organisation")
    d = c["programme_219_depense_constatee"]
    assert d and any(a["annee"] == d["annee"] and a["depense_constatee_eur"] == d["eur"]
                     for a in BUDGET["programmes"]["219"]["annees"])
