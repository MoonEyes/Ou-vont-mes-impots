"""Marchés publics de tous les acheteurs (pipeline/marches.py).

Tests unitaires (SIRET, nature, catégorie d'acheteur, motifs d'écart) et production complète sur un petit jeu
synthétique (DECP, stock SIRENE, doublons) : toujours lancés, sans réseau ni entrepôt. Tests des fichiers publiés si
site/data/marches existe.
"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "marches"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "docs"))
import marches as mp  # noqa: E402

duckdb = pytest.importorskip("duckdb")


# --- Identifiants synthétiques à clé valide --------------------------------------------------------------------------


def _cle(prefixe: str) -> str:
    return next(prefixe + str(c) for c in range(10) if mp.luhn(prefixe + str(c)))


def siren(n: int) -> str:
    return _cle(f"{n:08d}")


def siret(s: str, nic: int = 1) -> str:
    return _cle(f"{s}{nic:04d}")


# --- Unitaires -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("brut,attendu", [
    ("77605646700587", True), ("35600000065307", True),   # UGAP ; La Poste (règle propre : somme multiple de 5)
    ("7760564670058", False), ("776056467005870", False), ("", False), (None, False), ("FR12345678901", False),
    ("77605646700588", False), ("00000000000000", False), ("12345678900012", False), ("XXXXXXXXXXXXXX", False),
])
def test_siret_valide(brut, attendu):
    assert mp.siret_valide(brut) is attendu


def test_siren_genere_valide():
    assert mp.siren_valide(siren(12345678)) and mp.siret_valide(siret(siren(12345678), 27))
    assert not mp.siren_valide("123456789") and not mp.siren_valide("000000000")


@pytest.mark.parametrize("brut,attendu", [
    ("Marché", "Marché"), ("MARCHE", "Marché"), ("marché", "Marché"), ("Accord-cadre", "Accord-cadre"),
    ("ACCORD-CADRE", "Accord-cadre"), ("Accord cadre", "Accord-cadre"), ("MARCHE SUBSEQUENT", "Marché subséquent"),
    ("Marché subséquent", "Marché subséquent"), ("MARCHE DE PARTENARIAT", "Marché de partenariat"),
    ("Marché de défense ou de sécurité", "Marché de défense ou de sécurité"),
    (None, "Non renseignée"), ("  ", "Non renseignée"),
    ("Concession de service public", "hors champ"), ("Délégation de service public", "hors champ"),
    ("Concession de travaux", "hors champ"),
])
def test_nature_normalisee(brut, attendu):
    assert mp.nature_normalisee(brut) == attendu


def test_nature_inconnue_arrete_la_production():
    with pytest.raises(SystemExit):
        mp.nature_normalisee("Bail emphytéotique")


@pytest.mark.parametrize("source,cj,attendu", [
    ("Commune", "7210", ("Commune", "decp")), ("Établissement hospitalier", "7364", ("Établissement hospitalier", "decp")),
    ("État", "7113", ("État", "decp")), (None, "7389", (mp.CAT_EPA_NATIONAL, "sirene")),
    (None, "7361", (mp.CAT_EPA_LOCAL, "sirene")), (None, "7381", (mp.CAT_CONSULAIRE, "sirene")),
    (None, "7410", (mp.CAT_GIP, "sirene")), (None, "7470", (mp.CAT_AUTRE_PUBLIC, "sirene")),
    (None, "4150", (mp.CAT_REGIE, "sirene")), (None, "5599", (mp.CAT_SOCIETE, "sirene")),
    (None, "8110", (mp.CAT_SECU, "sirene")), (None, "9220", (mp.CAT_ASSO, "sirene")),
    (None, "", (mp.CAT_INCONNUE, "sirene")), (None, "1000", (mp.CAT_INCONNUE, "sirene")),
])
def test_categorie_acheteur(source, cj, attendu):
    assert mp.categorie_acheteur(source, cj) == attendu
    assert attendu[0] in mp.ORDRE_CATEGORIES


def test_categorie_source_inconnue_arrete_la_production():
    with pytest.raises(SystemExit):
        mp.categorie_acheteur("Ambassade", "7113")


def test_statut_siren_personnes_morales_seules():
    stock = {"1": ("5710", "ENTREPRISE A", "O"), "2": ("1000", "MARTIN PAUL", "O"), "3": ("2110", "INDIVISION X", "O"),
             "4": ("5710", "ENTREPRISE B", "P"), "5": ("5710", "[ND]", "O"), "6": ("", None, "O"),
             "7": ("5710", None, "O")}
    assert mp.statut_siren("1", stock) == ("pm", "5710", "ENTREPRISE A")
    assert mp.statut_siren("2", stock) == ("pp", None, None)      # entrepreneur individuel
    assert mp.statut_siren("3", stock) == ("pp", None, None)      # groupement de personnes physiques
    assert mp.statut_siren("4", stock) == ("nd", None, None)      # diffusion partielle
    assert mp.statut_siren("5", stock) == ("nd", None, None) and mp.statut_siren("7", stock) == ("nd", None, None)
    assert mp.statut_siren("6", stock) == ("in", None, None) and mp.statut_siren("9", stock) == ("in", None, None)
    assert mp.statut_siren(None, stock) == ("in", None, None)


@pytest.mark.parametrize("args,attendu", [
    (("hors champ", 2024, False, 10.0, None, True), "nature_hors_champ"),
    (("Marché", None, False, 10.0, None, True), "date_absente"),
    (("Marché", 1899, True, 10.0, None, True), "date_impossible"),
    (("Marché", 2018, False, 10.0, None, True), "hors_periode"),
    (("Marché", 2026, False, 10.0, None, True), "hors_periode"),
    (("Marché", 2024, False, None, None, True), "montant_non_renseigne"),
    (("Marché", 2024, False, 9e9, "aberrant", True), "montant_aberrant"),
    (("Marché", 2024, False, 5e6, "suspect", False), "montant_suspect"),
    (("Marché", 2024, False, -5.0, None, True), "montant_negatif"),
    (("Marché", 2024, False, 10.0, None, False), "siret_titulaire_invalide"),
    (("Marché", 2024, False, 2e9, None, False, True), "montant_serie_repetee"),
    (("Marché", 2024, False, 2e9, "suspect", True, True), "montant_suspect"),
    (("Marché", 2019, False, 0.0, None, True), "retenu"), (("Accord-cadre", 2025, False, 10.0, None, True), "retenu"),
])
def test_motif_ligne(args, attendu):
    assert mp.motif_ligne(*args) == attendu
    assert attendu == "retenu" or attendu in {m[0] for m in mp.MOTIFS}


def test_departement_et_euros():
    assert mp.departement("44") == "44" and mp.departement("2a") == "2A" and mp.departement("974") == "974"
    assert mp.departement("987") == "987" and mp.departement(None) is None and mp.departement("999") is None
    assert mp.departement("4") is None and mp.departement("FR") is None
    assert mp.eur(1_234_567_890) == 1234.57 and mp.eur(0) == 0.0


@pytest.mark.parametrize("brut,attendu", [
    ("45233140-2", "45"), ("45000000", "45"), ("72600000-6", "72"), (" 09310000 ", "09"), (None, "00"),
    ("", "00"), ("4523", "00"), ("99000000", "00"), ("XX000000", "00"),
])
def test_division_cpv(brut, attendu):
    assert mp.division_cpv(brut) == attendu
    assert attendu in mp.CPV_DIVISIONS or attendu == mp.CPV_ILLISIBLE


def test_divisions_cpv_et_regions_completes():
    assert len(mp.CPV_DIVISIONS) == 45 and all(len(k) == 2 and k.isdigit() for k in mp.CPV_DIVISIONS)
    metropole = [f"{i:02d}" for i in range(1, 96) if i != 20] + ["2A", "2B"]
    assert all(mp.region(d) not in (None, mp.COM) for d in metropole + ["971", "972", "973", "974", "976"])
    assert len(mp.REGION_DU_DEPARTEMENT) == len(metropole) + 5 and len(mp.REGIONS) == 18
    assert mp.region("44") == "52" and mp.region("2A") == "94" and mp.region("976") == "06"
    assert mp.region("975") == mp.region("987") == mp.region("988") == mp.COM and mp.region(None) is None


def test_colonnes_sensibles_jamais_lues():
    """Noms, objets, communes et coordonnées des DECP, noms et prénoms SIRENE : aucune de ces colonnes n'est lue."""
    code = inspect.getsource(mp)
    for motif in ("titulaire_nom", "acheteur_nom", "prenom", "nomUniteLegale", "nomUsage", "latitude", "longitude",
                  "commune_nom", "commune_code", "lieuExecution", "sexe"):
        assert motif not in code.replace("denominationUniteLegale", ""), motif
    assert "objet" not in mp.COLONNES
    assert [c for c in mp.COLONNES if c.endswith("_nom")] == ["acheteur_departement_nom"]


def test_sources_declarees_au_catalogue():
    cat = {s["id"]: s for s in json.loads((ROOT / "collecte" / "catalogue.json").read_text(encoding="utf-8"))["sources"]}
    assert cat[mp.ID_DECP]["dataset"] == cat[mp.ID_DOUBLONS]["dataset"] == "608c055b35eb4e6ee20eb325"
    assert cat[mp.ID_DECP].get("personnes_physiques"), "DECP : zone restreinte attendue (entrepreneurs individuels)"
    assert cat[mp.ID_DOUBLONS]["domaine"] == "marches"
    assert {t["classement"] for t in mp.RECHERCHE_PUBLIQUE["trouvailles"]} <= {
        "réutilisable tel quel", "à adapter", "inspiration seulement"}


def test_repere_oecp_source_ou_null():
    r = mp.REPERE_OECP
    assert r["saisie"] == "manuelle" and r["source_officielle"]["url"].startswith("https://www.economie.gouv.fr/")
    if r["montant_eur"] is None:
        assert r["page_consultee"] is None
    else:
        assert r["page_consultee"]["url"].startswith("https://") and r["annee"] == 2024
        assert abs(sum(d["montant_eur"] for d in r["detail_publie"]) - r["montant_eur"]) <= 0.2e9
        assert sum(d["nombre_marches"] for d in r["detail_publie"]) == r["nombre_marches"]


# --- Production sur un jeu synthétique -----------------------------------------------------------------------------------

COMMUNE, EPA, SANS_STOCK = siren(21440001), siren(18000001), siren(55500001)
UGAP = "776056467"
T1, T2, EI, ND, ABSENT = siren(30000001), siren(30000002), siren(40000001), siren(30000003), siren(30000004)
AUTRES = [siren(31000000 + i) for i in range(12)]
NOM_EI = "MARTIN PAUL ENTREPRENEUR"


def _lignes_decp() -> list[dict]:
    com, epa, ugap = siret(COMMUNE), siret(EPA), "77605646700587"
    d = dt.date

    def li(uid, ach, tit, montant, date, nature="Marché", cat="Commune", dep="44", mid=0, da=True, ano=None,
           type_="Travaux", cpv="45000000-7"):
        return {"uid": uid, "acheteur_id": ach, "titulaire_id": tit, "nature": nature, "type": type_,
                "montant": montant, "montant_anomalie": ano, "dateNotification": date, "modification_id": mid,
                "donneesActuelles": da, "acheteur_categorie": cat, "acheteur_departement_code": dep,
                "acheteur_departement_nom": "Loire-Atlantique" if dep == "44" else None, "sourceDataset": "source_a",
                "codeCPV": cpv,
                "titulaire_nom": "NE JAMAIS LIRE", "objet": "NE JAMAIS LIRE"}

    lignes = [
        li("u1", com, siret(T1), 100000.0, d(2024, 3, 1), nature="MARCHE"),
        li("u1", com, siret(T1), 100000.0, d(2024, 3, 1), nature="MARCHE"),                    # doublon (uid, titulaire)
        li("u2", com, siret(T1), 60000.0, d(2023, 2, 1), nature="Accord cadre", type_="Services"),
        li("u2", com, siret(EI), 60000.0, d(2023, 2, 1), nature="Accord cadre", type_="Services"),  # co-titulaire EI
        li("u3", com, siret(T2), 50.0, d(2022, 5, 1), da=False),                              # version antérieure
        li("u3", com, siret(T2), 80000.0, d(2024, 6, 1), mid=1),                             # version actuelle
        li("u4", com, siret(T1), 9e9, d(2024, 1, 1), ano="aberrant"),
        li("u5", com, siret(T1), 5e6, d(2024, 1, 1), ano="suspect"),
        li("u6", com, "FR123456", 7000.0, d(2024, 1, 1)),                                     # identifiant non SIRET
        li("u7", com, siret(T1), 1000.0, d(1899, 1, 1)),                                      # date impossible
        li("u7b", com, siret(T1), 1500.0, d(2031, 1, 1)),                                     # date postérieure à la collecte
        li("u8", com, siret(T1), 2000.0, d(2018, 12, 31)),                                    # hors période
        li("u9", com, siret(T1), None, d(2024, 1, 1)),                                        # montant non renseigné
        li("u10", com, siret(T1), 3000.0, d(2024, 1, 1), nature="Concession de service"),     # hors champ
        li("u11", epa, siret(ND), 40000.0, d(2025, 1, 1), cat=None, dep="75"),                # diffusion partielle
        li("u12", siret(EPA, 2), siret(ABSENT), 10000.0, d(2025, 1, 1), cat=None, dep="77"),  # absent du stock
        li("u13", ugap, siret(T1), 500000.0, d(2024, 4, 1), nature="ACCORD-CADRE", cat="EPIC", dep="77", cpv=None),
        li("u14", com, ugap, 20000.0, d(2024, 5, 1), type_="Fournitures", cpv="30200000"),   # la centrale est titulaire
        li("u15", com, siret(T2), 5000.0, d(2019, 1, 1), dep=None),                           # non localisé
        li("u16", siret(SANS_STOCK), siret(T1), 8000.0, d(2020, 1, 1), cat=None, dep="44"),   # acheteur non nommé
    ]
    lignes += [li(f"v{i}", com, siret(s), 1000.0 * (i + 1), d(2021, 1, 1)) for i, s in enumerate(AUTRES)]
    # Série : trois marchés du même acheteur, même année, même montant >= 100 M€ (règle 8) ; le troisième a un
    # titulaire sans SIRET valide (la série passe avant ce motif).
    lignes += [li(f"s{i}", com, siret(T2) if i < 2 else "FR999", 2e8, d(2022, 7, 1), cpv="72600000-6")
               for i in range(3)]
    return lignes


def _stock() -> list[tuple]:
    pm = [(COMMUNE, 7210, "COMMUNE DE TEST", None, "O"), (EPA, 7389, "ETABLISSEMENT PUBLIC DE TEST", None, "O"),
          (UGAP, 4110, "UNION DES GROUPEMENTS D'ACHATS PUBLICS", None, "O"),
          (T1, 5710, "ENTREPRISE UN", None, "O"), (T2, 5499, None, "ENTREPRISE DEUX", "O"),
          (EI, 1000, NOM_EI, NOM_EI, "O"), (ND, 5710, "SOCIETE NON DIFFUSIBLE", None, "P")]
    return pm + [(s, 5710, f"FOURNISSEUR {i:02d}", None, "O") for i, s in enumerate(AUTRES)]


@pytest.fixture(scope="module")
def production(tmp_path_factory):
    import pyarrow as pa
    import pyarrow.parquet as pq
    tmp = tmp_path_factory.mktemp("marches")
    lignes = _lignes_decp()
    pq.write_table(pa.table({k: [li[k] for li in lignes] for k in lignes[0]}), tmp / "decp.parquet")
    st = _stock()
    pq.write_table(pa.table({
        "siren": [s[0] for s in st], "categorieJuridiqueUniteLegale": pa.array([s[1] for s in st], pa.int64()),
        "denominationUniteLegale": [s[2] for s in st], "denominationUsuelle1UniteLegale": [s[3] for s in st],
        "statutDiffusionUniteLegale": [s[4] for s in st]}), tmp / "stock.parquet")
    pq.write_table(pa.table({"sourceDataset": ["source_a"], "unique": [0.75]}), tmp / "doublons.parquet")
    mpatch = pytest.MonkeyPatch()
    mpatch.setenv("SOURCE_DATE_EPOCH", "1794873600")  # 2026-11-17
    sorties = []
    for nom in ("a", "b"):
        mp.produire(tmp / nom, tmp / "decp.parquet", tmp / "stock.parquet", tmp / "doublons.parquet")
        sorties.append(tmp / nom)
    mpatch.undo()
    return sorties


def _lire(dossier: Path, rel: str) -> dict:
    return json.loads((dossier / rel).read_text(encoding="utf-8"))


def test_synthetique_regles_de_qualite(production):
    idx = _lire(production[0], "index.json")
    regles = {r["id"]: r for r in idx["regles_qualite"]}
    attendu = {"versions_anterieures": (1, None), "doublons_uid_titulaire": (1, None), "nature_hors_champ": (1, 3000.0),
               "date_absente": (0, 0.0), "date_impossible": (2, 2500.0), "hors_periode": (1, 2000.0),
               "montant_non_renseigne": (1, None), "montant_aberrant": (1, 9e9), "montant_suspect": (1, 5e6),
               "montant_negatif": (0, 0.0), "montant_serie_repetee": (3, 6e8), "siret_titulaire_invalide": (1, 7000.0)}
    assert {k: (v["lignes"], v["montant_eur"]) for k, v in regles.items()} == attendu
    assert [r["id"] for r in idx["regles_qualite"]][2:] == [m[0] for m in mp.MOTIFS]
    assert idx["anomalies_source"]["aberrant"] == {"lignes": 1, "marches": 1, "montant_declare_eur": 9e9}
    assert idx["anomalies_source"]["suspect"] == {"lignes": 1, "marches": 1, "montant_declare_eur": 5e6}
    t = idx["totaux"]
    retenu = 100000 + 60000 + 80000 + 40000 + 10000 + 500000 + 20000 + 5000 + 8000 + sum(1000 * (i + 1) for i in range(12))
    assert t["total_retenu_eur"] == retenu and t["lignes_retenues"] == 22 and t["marches_retenus"] == 21
    assert t["lignes_source"] == len(_lignes_decp()) and t["lignes_dedoublonnees"] == t["lignes_source"] - 2
    # conservation : retenu + chaque motif d'écart = total des lignes actuelles dédoublonnées
    assert t["montant_dedoublonne_eur"] == pytest.approx(
        retenu + sum(r["montant_eur"] or 0 for r in idx["regles_qualite"]), abs=0.01)


def test_synthetique_annee_de_la_notification_initiale_et_cotitulaires(production):
    an = {p["annee"]: p for p in _lire(production[0], "annees.json")["par_annee"]}
    assert an[2022]["total_eur"] == 80000.0            # u3 : montant actuel, année de la notification initiale
    assert an[2023]["total_eur"] == 60000.0 and an[2023]["marches"] == 1 and an[2023]["lignes"] == 2
    assert an[2023]["nommes_eur"] == 30000.0           # moitié du marché u2 ; l'autre moitié (EI) est agrégée
    assert an[2023]["agrege_confidentialite"]["dont_personnes_physiques_eur"] == 30000.0
    assert [n["nature"] for n in an[2023]["par_nature"]] == ["Accord-cadre"]
    assert an[2024]["total_eur"] == 620000.0
    assert {n["nature"]: n["montant_eur"] for n in an[2024]["par_nature"]} == {"Marché": 120000.0, "Accord-cadre": 500000.0}
    assert an[2024]["ecartes"]["montant_aberrant"] == {"lignes": 1, "montant_eur": 9e9}
    assert an[2024]["ecartes"]["montant_suspect"] == {"lignes": 1, "montant_eur": 5e6}
    assert an[2024]["ecartes"]["montant_non_renseigne"] == {"lignes": 1, "montant_eur": None}   # jamais 0
    assert an[2024]["ecartes"]["siret_titulaire_invalide"] == {"lignes": 1, "montant_eur": 7000.0}
    assert an[2022]["ecartes"]["montant_serie_repetee"] == {"lignes": 3, "montant_eur": 6e8}
    assert an[2022]["total_eur"] == 80000.0            # la série n'entre pas dans le total de l'année


def test_synthetique_series_repetees_publiees(production):
    sr = _lire(production[0], "index.json")["series_repetees"]
    assert sr["seuil_eur"] == mp.SERIE_SEUIL_EUR and sr["marches_minimum"] == mp.SERIE_MIN_MARCHES
    assert {p["annee"]: (p["series"], p["marches"], p["lignes"], p["montant_declare_eur"]) for p in sr["par_annee"]}[2022] \
        == (1, 3, 3, 6e8)
    assert sr["principales"] == [{"annee": 2022, "siren": COMMUNE, "denomination": "COMMUNE DE TEST",
                                  "categorie": "Commune", "marches": 3, "montant_unitaire_eur": 2e8,
                                  "montant_declare_eur": 6e8}]
    gros = _lire(production[0], "index.json")["plus_gros_marches"]["marches"]
    assert gros[0]["montant_eur"] == 500000.0 and gros[0]["acheteur"] == "UNION DES GROUPEMENTS D'ACHATS PUBLICS"
    assert all(g["montant_eur"] < 2e8 for g in gros)


def test_synthetique_regions_secteurs_titulaires_acheteurs(production):
    idx = _lire(production[0], "index.json")
    total = idx["totaux"]["total_retenu_eur"]
    reg = _lire(production[0], "regions.json")
    assert [(r["region"], r["departements"]) for r in reg["regions"]] == [("11", ["75", "77"]), ("52", ["44"])]
    assert reg["non_localise"]["total_eur"] == 5000.0
    assert sum(r["total_eur"] for r in reg["regions"]) + 5000.0 == pytest.approx(total)
    sec = {s["division"]: s for s in _lire(production[0], "secteurs.json")["secteurs"]}
    assert set(sec) == {"30", "45", "00"} and sec["00"]["total_eur"] == 500000.0 and sec["30"]["total_eur"] == 20000.0
    assert sec["00"]["libelle"] == mp.LIBELLE_CPV_ILLISIBLE and sec["45"]["libelle"] == "Travaux de construction"
    assert sum(s["total_eur"] for s in sec.values()) == pytest.approx(total)
    tit = _lire(production[0], "titulaires.json")
    assert tit["titulaires"][0]["siren"] == T1 and EI not in {t["siren"] for t in tit["titulaires"]}
    assert (sum(t["total_eur"] for t in tit["titulaires"]) + tit["autres_personnes_morales"]["montant_eur"]
            + tit["agrege_confidentialite"]["montant_eur"]) == pytest.approx(total)
    a23 = {p["annee"]: p for p in tit["par_annee"]}[2023]
    assert [t["siren"] for t in a23["titulaires"]] == [T1] and a23["agrege_confidentialite"]["montant_eur"] == 30000.0
    ach = _lire(production[0], "acheteurs.json")
    noms = {a["siren"]: a for a in ach["acheteurs"]}
    assert set(noms) == {COMMUNE, UGAP, EPA} and noms[EPA]["departements"] == 2 and noms[UGAP]["centrale_achat"]
    assert ach["acheteurs_non_nommes"] == {"nombre": 1, "marches": 1, "montant_eur": 8000.0}
    assert sum(a["total_eur"] for a in ach["acheteurs"]) + 8000.0 == pytest.approx(total)


def test_synthetique_categories_et_departements(production):
    cats = {c["categorie"]: c for c in _lire(production[0], "categories.json")["categories"]}
    assert cats["Commune"]["origine"] == "decp" and cats["EPIC"]["total_eur"] == 500000.0
    assert cats[mp.CAT_EPA_NATIONAL]["origine"] == "sirene" and cats[mp.CAT_EPA_NATIONAL]["total_eur"] == 50000.0
    assert cats[mp.CAT_INCONNUE]["total_eur"] == 8000.0
    idx = _lire(production[0], "index.json")
    assert sum(c["total_eur"] for c in cats.values()) == pytest.approx(idx["totaux"]["total_retenu_eur"])
    deps = _lire(production[0], "departements.json")
    assert [d["departement"] for d in deps["departements"]] == ["44", "75", "77"]
    assert deps["non_localise"]["total_eur"] == 5000.0
    assert sum(d["total_eur"] for d in deps["departements"]) + 5000.0 == pytest.approx(idx["totaux"]["total_retenu_eur"])
    d44 = _lire(production[0], "departements/44.json")
    assert d44["nom"] == "Loire-Atlantique" and d44["acheteurs_total"] == 2 and len(d44["acheteurs"]) == 1
    assert d44["acheteurs_non_nommes"] == {"nombre": 1, "marches": 1, "montant_eur": 8000.0}
    assert d44["montants_eur"][mp.ANNEES.index(2025)] is None        # aucune ligne : null, jamais 0


def test_synthetique_top_titulaires_et_conservation(production):
    d44 = _lire(production[0], "departements/44.json")
    a = d44["acheteurs"][0]
    assert a["siren"] == COMMUNE and a["denomination"] == "COMMUNE DE TEST" and a["categorie"] == "Commune"
    assert len(a["titulaires"]) == mp.TOP_TITULAIRES
    montants = [t["montant_eur"] for t in a["titulaires"]]
    assert montants == sorted(montants, reverse=True) and a["titulaires"][0]["siren"] == T1
    assert a["titulaires"][0]["montant_eur"] == 130000.0             # u1 + moitié de u2
    assert {t["siren"]: t["denomination"] for t in a["titulaires"]}[T2] == "ENTREPRISE DEUX"   # dénomination usuelle
    assert a["autres_titulaires"]["nombre"] == 15 - mp.TOP_TITULAIRES
    assert a["agrege_confidentialite"] == {"montant_eur": 30000.0, "lignes": 1}
    assert (sum(montants) + a["autres_titulaires"]["montant_eur"] + a["agrege_confidentialite"]["montant_eur"]
            == pytest.approx(a["total_eur"]))
    d75 = _lire(production[0], "departements/75.json")["acheteurs"][0]
    assert d75["titulaires"] == [] and d75["agrege_confidentialite"] == {"montant_eur": 40000.0, "lignes": 1}


def test_synthetique_aucune_personne_physique_ni_colonne_sensible(production):
    for f in production[0].rglob("*.json"):
        texte = f.read_text(encoding="utf-8")
        for interdit in (EI, NOM_EI, "MARTIN", ND, "NON DIFFUSIBLE", ABSENT, "NE JAMAIS LIRE", SANS_STOCK):
            assert interdit not in texte, f"{f.name} : {interdit}"
    idx = _lire(production[0], "index.json")
    c = idx["totaux"]["agrege_confidentialite"]
    assert (c["dont_personnes_physiques_eur"], c["dont_diffusion_partielle_eur"], c["dont_siren_introuvable_eur"]) == (
        30000.0, 40000.0, 10000.0)
    assert idx["totaux"]["nommes_eur"] + c["montant_eur"] == pytest.approx(idx["totaux"]["total_retenu_eur"])


def test_synthetique_centrale_d_achat_des_deux_cotes(production):
    idx = _lire(production[0], "index.json")
    (c,) = idx["centrales_achat"]["centrales"]
    assert c["siren"] == UGAP and c["comme_acheteur"]["montant_eur"] == 500000.0
    assert c["comme_titulaire"] == {"marches": 1, "montant_eur": 20000.0,
                                    "montants_eur": [None, None, None, None, None, 20000.0, None]}
    assert "double compte" in idx["centrales_achat"]["note"]
    assert idx["doublons_entre_sources"]["sources"] == [
        {"source": "source_a", "lignes_retenues": 22, "part_unique_pct": 75.0}]
    r = idx["repere_oecp"]
    assert r["montant_eur"] == mp.REPERE_OECP["montant_eur"] and r["montant_ici_eur"] == 620000.0


def test_synthetique_conforme_aux_schemas_et_reproductible(production):
    import valider_contrat as vc
    js = pytest.importorskip("jsonschema")
    schemas = {"index.json": "marches_index", "annees.json": "marches_annees", "categories.json": "marches_categories",
               "departements.json": "marches_departements", "regions.json": "marches_regions",
               "secteurs.json": "marches_secteurs", "titulaires.json": "marches_titulaires",
               "acheteurs.json": "marches_acheteurs"}
    fichiers = sorted(p.relative_to(production[0]).as_posix() for p in production[0].rglob("*.json"))
    assert fichiers == sorted(p.relative_to(production[1]).as_posix() for p in production[1].rglob("*.json"))
    for rel in fichiers:
        a, b = (production[0] / rel).read_bytes(), (production[1] / rel).read_bytes()
        assert a == b, f"{rel} : deux productions différentes"
        assert len(a) < mp.MAX_OCTETS
        doc = json.loads(a)
        assert doc["millesime"] and doc["source"] and doc["collecte_le"] == "2026-11-17"
        nom = schemas.get(rel, "marches_departement")
        assert not vc.erreurs(vc.validateur(js, f"{nom}.schema.json"), doc), rel


def test_schema_refuse_un_entrepreneur_individuel(production):
    import valider_contrat as vc
    js = pytest.importorskip("jsonschema")
    doc = _lire(production[0], "departements/44.json")
    doc["acheteurs"][0]["titulaires"][0]["categorie_juridique"] = "1000"
    assert vc.erreurs(vc.validateur(js, "marches_departement.schema.json"), doc)
    doc = _lire(production[0], "departements/44.json")
    doc["acheteurs"][0]["titulaires"][0]["prenom"] = "x"
    assert vc.erreurs(vc.validateur(js, "marches_departement.schema.json"), doc)


def test_decoupage_des_gros_departements(production, tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SEUIL_DECOUPE", 1)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1794873600")
    src = production[0].parent
    mp.produire(tmp_path, src / "decp.parquet", src / "stock.parquet", src / "doublons.parquet")
    import valider_contrat as vc
    js = pytest.importorskip("jsonschema")
    deps = {d["departement"]: d for d in _lire(tmp_path, "departements.json")["departements"]}
    assert deps["44"]["fichiers"] == ["marches/departements/44.json"]         # un seul acheteur nommé : pas de partie
    assert deps["77"]["fichiers"] == ["marches/departements/77_1.json", "marches/departements/77_2.json"]
    parties = [_lire(tmp_path, Path(f).relative_to("marches").as_posix()) for f in deps["77"]["fichiers"]]
    assert [(p["partie"], p["parties"], len(p["acheteurs"])) for p in parties] == [(1, 2, 1), (2, 2, 1)]
    assert [p["acheteurs"][0]["siren"] for p in parties] == [UGAP, EPA]
    assert sum(p["acheteurs"][0]["total_eur"] for p in parties) == deps["77"]["total_eur"] == 510000.0
    for p in parties:
        assert not vc.erreurs(vc.validateur(js, "marches_departement.schema.json"), p)


# --- Fichiers publiés --------------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                            reason="site/data/marches absent : lancer `python pipeline/marches.py produire`")


def charger(rel: str) -> dict:
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@publie
def test_fichiers_sous_5_mo_et_entete():
    fichiers = sorted(DOSSIER.rglob("*.json"))
    assert len(fichiers) > 100
    for f in fichiers:
        assert f.stat().st_size < mp.MAX_OCTETS, f.name
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["millesime"].startswith("Marchés notifiés de 2019 à 2025") and "data.gouv.fr" in doc["source"]
        assert doc["unite"].startswith("euros HT")


@publie
def test_totaux_coherents_entre_fichiers():
    idx = charger("marches/index.json")
    total = idx["totaux"]["total_retenu_eur"]
    assert total > 500e9 and idx["annees"] == mp.ANNEES
    an = charger("marches/annees.json")["par_annee"]
    assert [p["annee"] for p in an] == mp.ANNEES
    assert sum(p["total_eur"] for p in an) == pytest.approx(total, abs=1)
    assert [(p["annee"], p["total_eur"]) for p in an] == [(p["annee"], p["total_eur"]) for p in idx["par_annee"]]
    for p in an:
        assert sum(n["montant_eur"] for n in p["par_nature"]) == pytest.approx(p["total_eur"], abs=1)
        assert sum(t["montant_eur"] for t in p["par_type"]) == pytest.approx(p["total_eur"], abs=1)
        assert p["nommes_eur"] + p["agrege_confidentialite"]["montant_eur"] == pytest.approx(p["total_eur"], abs=1)
    cats = charger("marches/categories.json")["categories"]
    assert sum(c["total_eur"] for c in cats) == pytest.approx(total, abs=1)
    assert {"Commune", "Département", "Région", "Établissement hospitalier", "État", "EPIC"} <= {c["categorie"] for c in cats}
    for c in cats:
        assert sum(p["montant_eur"] for p in c["par_annee"]) == pytest.approx(c["total_eur"], abs=1)
    deps = charger("marches/departements.json")
    somme = sum(d["total_eur"] for d in deps["departements"]) + (deps["non_localise"] or {"total_eur": 0})["total_eur"]
    assert somme == pytest.approx(total, abs=1)
    # conservation des règles de qualité
    assert idx["totaux"]["montant_dedoublonne_eur"] == pytest.approx(
        total + sum(r["montant_eur"] or 0 for r in idx["regles_qualite"]), abs=1)
    regles = {r["id"]: r for r in idx["regles_qualite"]}
    assert regles["montant_aberrant"]["lignes"] > 0 and regles["montant_suspect"]["lignes"] > 0
    assert regles["montant_aberrant"]["montant_eur"] > 0 and regles["montant_suspect"]["montant_eur"] > 0
    assert regles["montant_non_renseigne"]["montant_eur"] is None


@publie
def test_departements_conservation_liens_et_personnes_morales():
    deps = charger("marches/departements.json")["departements"]
    assert len(deps) >= 100
    for d in deps:
        somme, nommes, non_nommes = 0.0, 0, None
        for rel in d["fichiers"]:
            doc = charger(rel)
            assert doc["departement"] == d["departement"] and doc["total_eur"] == d["total_eur"]
            non_nommes = doc["acheteurs_non_nommes"]
            for a in doc["acheteurs"]:
                nommes += 1
                somme += a["total_eur"]
                assert a["categorie_juridique"][0] in "23456789" and a["denomination"]
                assert len(a["titulaires"]) <= mp.TOP_TITULAIRES
                assert all(t["categorie_juridique"][0] in "23456789" and t["denomination"] for t in a["titulaires"])
                conserve = (sum(t["montant_eur"] for t in a["titulaires"]) + a["autres_titulaires"]["montant_eur"]
                            + a["agrege_confidentialite"]["montant_eur"])
                assert conserve == pytest.approx(a["total_eur"], abs=1), (d["departement"], a["siren"])
                assert sum(m or 0 for m in a["montants_eur"]) == pytest.approx(a["total_eur"], abs=1)
        assert somme + non_nommes["montant_eur"] == pytest.approx(d["total_eur"], abs=1), d["departement"]
        assert nommes + non_nommes["nombre"] == d["acheteurs"], d["departement"]


@publie
def test_series_repetees_et_nouveaux_fichiers_publies():
    idx = charger("marches/index.json")
    an = {p["annee"]: p for p in charger("marches/annees.json")["par_annee"]}
    sr = {p["annee"]: p for p in idx["series_repetees"]["par_annee"]}
    for a, p in an.items():
        assert p["ecartes"]["montant_serie_repetee"]["montant_eur"] == sr[a]["montant_declare_eur"]
    assert idx["series_repetees"]["principales"] and idx["plus_gros_marches"]["marches"]
    total = idx["totaux"]["total_retenu_eur"]
    reg = charger("marches/regions.json")
    assert len(reg["regions"]) >= 18
    assert sum(r["total_eur"] for r in reg["regions"]) + (reg["non_localise"] or {"total_eur": 0})["total_eur"] \
        == pytest.approx(total, abs=1)
    assert sum(s["total_eur"] for s in charger("marches/secteurs.json")["secteurs"]) == pytest.approx(total, abs=1)
    tit = charger("marches/titulaires.json")
    assert all(t["categorie_juridique"][0] in "23456789" for t in tit["titulaires"])
    assert (sum(t["total_eur"] for t in tit["titulaires"]) + tit["autres_personnes_morales"]["montant_eur"]
            + tit["agrege_confidentialite"]["montant_eur"]) == pytest.approx(total, abs=1)
    ach = charger("marches/acheteurs.json")
    assert (sum(a["total_eur"] for a in ach["acheteurs"]) + ach["autres_acheteurs_nommes"]["montant_eur"]
            + ach["acheteurs_non_nommes"]["montant_eur"] + ach["acheteur_illisible"]["montant_eur"]) \
        == pytest.approx(total, abs=1)


@publie
def test_repere_oecp_centrales_et_recherche_publies():
    idx = charger("marches/index.json")
    r = idx["repere_oecp"]
    assert r["annee"] == 2024 and r["saisie"] == "manuelle" and r["montant_ici_eur"] is not None
    assert (r["montant_eur"] is None) == (r["page_consultee"] is None)
    assert any("economie.gouv.fr" in s["source"] for s in idx["sources_inaccessibles"])
    centrales = {c["siren"]: c for c in idx["centrales_achat"]["centrales"]}
    assert "776056467" in centrales and centrales["776056467"]["comme_acheteur"]["montant_eur"] > 0
    assert "double compte" in idx["centrales_achat"]["note"]
    assert idx["recherche_publique"]["trouvailles"] and idx["doublons_entre_sources"]["sources"]
    assert idx["totaux"]["agrege_confidentialite"]["dont_personnes_physiques_eur"] > 0
