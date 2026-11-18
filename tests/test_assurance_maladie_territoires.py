"""Assurance maladie par poste, par département et ONDAM (pipeline/assurance_maladie_territoires.py) : règles du
module et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "assurance_maladie_territoires"
sys.path.insert(0, str(ROOT / "pipeline"))
import assurance_maladie_territoires as amt  # noqa: E402


# --- fonctions pures (toujours testées) ------------------------------------------------------------------------------

def test_masque_jamais_zero():
    for v in (None, "", "NS", "NC", " ", True, "n.d."):
        assert amt.montant(v) is None, v
    assert amt.montant("0") == 0 and amt.montant(0) == 0
    assert amt.montant("168508748") == 168508748 and amt.montant("1 234") == 1234 and amt.montant(12.6) == 13
    assert amt.md("113,2") == 113.2 and amt.md("-0,5") == -0.5 and amt.pct("-5,6%") == -5.6


def test_codes_departement():
    for c in ("01", "19", "2A", "2B", "21", "95", "971", "976"):
        assert amt.est_departement(c), c
    for c in ("20", "96", "999", "975", "", None, "99"):
        assert not amt.est_departement(c), c
    codes = ["971", "2B", "01", "21", "2A", "95", "19"]
    assert sorted(codes, key=amt.cle_dep) == ["01", "19", "2A", "2B", "21", "95", "971"]


def test_sous_postes_sans_sigle_seul():
    for source, lib in amt.LIBELLES_SOUS_POSTES.items():
        for sigle in ("MCO", "SSR", "HAD", "AT/MP", "ATMP", "LPP"):
            assert sigle not in lib.split(), (source, lib)
    assert amt.sous_poste_id("Médicaments remboursés") == "medicaments"
    assert amt.sous_poste_id("Soins d'autres paramédicaux remboursés") == "soins_d_autres_paramedicaux"


def _ligne(annee, n1, n2, montant, type_somme="Partiel"):
    return {"annee": f"{annee}-01-01", "patho_niv1": "Total consommants tous régimes", "dep_niv_1": n1,
            "dep_niv_2": n2, "montant": montant, "type_somme": type_somme, "tri": 1.0}


def test_postes_controle_somme():
    lignes = [_ligne(2024, "Dépenses", "Total des dépenses remboursées", 300, "Total")]
    for n1, tot, sous in (("Soins de ville", "Total soins de ville remboursés", "Médicaments remboursés"),
                          ("Hospitalisations (tous secteurs)", "Total hospitalisations (tous secteurs) remboursées",
                           "Hospitalisations séjour MCO secteur public remboursées"),
                          ("Prestations en espèces", "Total prestations en espèces remboursées",
                           "Prestations d'invalidité remboursées")):
        lignes += [_ligne(2024, n1, tot, 100, "Total"), _ligne(2024, n1, sous, 100)]
    r = amt.lire_postes(lignes)
    assert r["annees"] == [2024] and [p["id"] for p in r["postes"]][:2] == ["total", "soins_de_ville"]
    assert all(c["ecart_eur"] == 0 for c in r["controles"])
    lignes[-1] = _ligne(2024, "Prestations en espèces", "Prestations d'invalidité remboursées", 50_000)
    with pytest.raises(SystemExit):
        amt.lire_postes(lignes)
    with pytest.raises(SystemExit):  # sous-poste inconnu : libellé à écrire avant publication
        amt.lire_postes(lignes[:-1] + [_ligne(2024, "Prestations en espèces", "Nouveau poste remboursé", 100)])


def test_ondam_lu_dans_le_texte():
    t2025 = (ROOT / "data" / "lake" / "secu" / "secu_placss2025_annexe3.pdf")
    t2024 = (ROOT / "data" / "lake" / "secu" / "secu_placss2024_annexe3.pdf")
    if not (t2025.exists() and t2024.exists()):
        pytest.skip("entrepôt absent")
    r = amt.lire_ondam(amt.texte_pdf(amt.SOURCES["secu_placss2025_annexe3"]["fichier"]),
                       amt.texte_pdf(amt.SOURCES["secu_placss2024_annexe3"]["fichier"]))
    tot = r["lignes"][0]["annees"]
    assert tot["2025"]["objectif_initial_md"] == 265.9 and tot["2025"]["constat_md"] == 265.4
    assert tot["2024"]["objectif_initial_md"] == 254.9 and tot["2024"]["constat_md"] == 256.4
    with pytest.raises(SystemExit):
        amt.lire_ondam("texte sans tableau", "rien")


# --- fichiers publiés ----------------------------------------------------------------------------------------------

def charger(nom):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent (produire d'abord)")
    return json.loads(p.read_text(encoding="utf-8"))


def test_entetes_et_tailles():
    for nom in ("index.json", "postes.json", "departements.json", "ondam.json"):
        d = charger(nom)
        assert d["millesime"] and d["source"].startswith("http"), nom
        assert (DOSSIER / nom).stat().st_size < amt.MAX_OCTETS, nom


def test_postes_coherents():
    d = charger("postes.json")
    n = len(d["annees"])
    ids = {p["id"] for p in d["postes"]}
    for p in d["postes"]:
        assert len(p["montants_eur"]) == n
        assert p["parent"] is None or p["parent"] in ids
    tot = next(p for p in d["postes"] if p["id"] == "total")["montants_eur"]
    grands = [p["montants_eur"] for p in d["postes"] if p["niveau"] == 1]
    for i in range(n):
        if tot[i] is not None and all(g[i] is not None for g in grands):
            assert abs(tot[i] - sum(g[i] for g in grands)) <= max(1000, tot[i] * 1e-6)


def test_departements_coherents():
    d = charger("departements.json")
    n = len(d["annees"])
    assert len(d["departements"]) >= 101 and "44" in d["departements"] and "2A" in d["departements"]
    postes = {p["id"] for p in d["postes_prescription"]}
    for code, f in d["departements"].items():
        assert set(f["prescriptions"]) == postes, code
        for serie in f["prescriptions"].values():
            assert len(serie) == n and all(v is None or v >= 0 for v in serie)
        for h in f["honoraires"].values():
            assert len(h["sans_depassement"]) == n and len(h["depassements"]) == n
    # écarts publiés (ligne France face à la somme) : faibles sauf masques du secret statistique
    col = d["ecarts_somme_france"]["colonnes"]
    for ligne in d["ecarts_somme_france"]["lignes"]:
        e = dict(zip(col, ligne))
        if e["departements_masques"] == 0:
            assert abs(e["ecart_eur"]) <= max(1000, abs(e["france_eur"]) * 1e-4), e


def test_ondam_coherent():
    d = charger("ondam.json")
    ids = [l["id"] for l in d["lignes"]]
    assert ids[0] == "total" and len(ids) == len(set(ids))
    for c in d["controles"]:
        assert abs(c["ecart_arrondi_md"]) <= 0.35
    for l in d["lignes"]:
        a = l["annees"]["2025"]
        assert a["constat_md"] is not None and a["objectif_initial_md"] is not None


def test_index_renvois_et_ecarts():
    d = charger("index.json")
    for k, f in d["fichiers"].items():
        assert (ROOT / "site" / "data" / f).exists(), k
    assert d["ecarts"] and all(e["valeur_md"] != e["autre_valeur_md"] for e in d["ecarts"])
    assert "secu" in d["liens"] and "sante_etablissements" in d["liens"]
    assert all(t["verdict"] for t in d["recherche_publique"]["trouvailles"])


def test_aucune_personne_ni_professionnel_nomme():
    texte = (DOSSIER / "departements.json").read_text(encoding="utf-8") if (DOSSIER / "departements.json").exists() \
        else pytest.skip("absent")
    for interdit in ("nom_professionnel", "prenom", "adresse", "rpps", "finess"):
        assert f'"{interdit}"' not in texte
