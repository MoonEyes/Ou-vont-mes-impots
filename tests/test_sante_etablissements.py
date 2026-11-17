"""Établissements de santé et médico-sociaux (pipeline/sante_etablissements.py) : fonctions, cohérence des fichiers
publiés, confidentialité, sans réseau."""
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "sante_etablissements"
sys.path.insert(0, str(ROOT / "pipeline"))
import sante_etablissements as se  # noqa: E402
import sirene  # noqa: E402


# --- fonctions (sans fichier) ------------------------------------------------------------------------------------

def test_nombre_absent_jamais_zero():
    assert se.nombre("110,3") == 110.3 and se.nombre("    30618190") == 30618190.0 and se.nombre(12) == 12.0
    for absent in (None, "", "   ", ".", ".z", ".v", ".m", "nc"):
        assert se.nombre(absent) is None, absent
    assert se.nombre("0") == 0.0 and se.entier("0") == 0
    assert se.entier("78") == 78 and se.entier(".") is None


def test_departement_et_codes_d_outre_mer():
    assert se.departement("44109") == "44" and se.departement("2A004") == "2A" and se.departement("97105") == "971"
    assert se.departement("97611") == "976" and se.departement(None) is None and se.departement("441") is None
    assert se.departement_ccam("9A") == "971" and se.departement_ccam("9D") == "974"
    assert se.departement_ccam("98") == "976" and se.departement_ccam("2a") == "2A" and se.departement_ccam("1") == "01"
    assert se.departement_ccam("") is None


def test_secteur_et_domaine():
    assert se.secteur("13") == "public" and se.secteur("60") == "prive_non_lucratif"
    assert se.secteur("95") == "prive_commercial" and se.secteur(None) is None and se.secteur("xx") is None
    assert se.domaine("1102") == "hospitalier" and se.domaine("4401") == "social_medico_social"
    assert se.domaine("6101") == "formation" and se.domaine(None) == "non_classe" and se.domaine("9999") == "non_classe"


def test_denomination_avec_titre_de_personne_jamais_publiee():
    for nom in ("CLINIQUE DU DOCTEUR DUPONT", "Cabinet Martin", "SELARL DR X", "RESIDENCE MME Y", "M. Z", ""):
        assert se.nom_publiable(nom) is None, nom
    assert se.nom_publiable(None) is None
    assert se.nom_publiable("CENTRE  HOSPITALIER DE  SAINT NAZAIRE") == "CENTRE HOSPITALIER DE SAINT NAZAIRE"
    assert se.nom_publiable("EHPAD LES PRIMEVERES") and se.nom_publiable("CENTRE MEDICO PSYCHOLOGIQUE")


def test_motif_non_nomme_personne_morale_seulement():
    ej = {"statut": "13", "siren": "264400136", "nom": "CHU"}
    e = {"ej": ej, "nom": "CHU SITE NORD"}
    assert se.motif_non_nomme(e, {"264400136": {"cj": "7364", "trouve": True}}) is None
    assert se.motif_non_nomme(e, {}) == "categorie_juridique_non_verifiee"
    assert se.motif_non_nomme(e, {"264400136": {"cj": "1000", "trouve": True}}) == "personne_physique"
    assert se.motif_non_nomme(e, {"264400136": {"cj": None, "trouve": False}}) == "siren_inconnu_de_sirene"
    assert se.motif_non_nomme({"ej": {**ej, "statut": "70"}, "nom": "X"}, {}) == "personne_physique"
    assert se.motif_non_nomme({"ej": {**ej, "siren": None}, "nom": "X"}, {}) == "siren_absent"
    assert se.motif_non_nomme({"ej": ej, "nom": "CLINIQUE DU DR X"}, {"264400136": {"cj": "5710", "trouve": True}}) \
        == "titre_de_personne_dans_la_denomination"


def test_bornes_des_prix():
    assert se.dans_bornes("prix_hebergement_chambre_seule_eur", 70.0)
    assert not se.dans_bornes("prix_hebergement_chambre_seule_eur", 7000.0)
    assert not se.dans_bornes("prix_hebergement_chambre_seule_eur", None)
    assert se.dans_bornes("tarif_dependance_gir_5_6_eur", 6.1) and not se.dans_bornes("tarif_dependance_gir_5_6_eur", 0)


def test_flux_json_lit_un_tableau_objet_par_objet(tmp_path):
    doc = {"schemaVersion": "v1", "gco": [{"a": 1}], "pmej": [{"n": i, "t": "x" * 50, "l": [{"k": "]"}]} for i in range(500)]}
    p = tmp_path / "f.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    assert list(se.flux_json(p, "pmej")) == doc["pmej"]
    assert list(se.flux_json(p, "gco")) == doc["gco"]
    assert list(se.flux_json(p, "absent")) == []


def test_perimetre_exclut_exercice_liberal_commerce_laboratoires():
    assert set(se.AGREGATS_EXCLUS) == {"2103", "3101", "3201"} and se.STATUT_PERSONNE_PHYSIQUE == "70"


# --- fichiers publiés ----------------------------------------------------------------------------------------------

publies = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                             reason="site/data/sante_etablissements absent : lancer `produire`")


def charger(rel):
    return json.loads((SITE / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("sante_etablissements/index.json")


@pytest.fixture(scope="module")
def par_dep():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((DOSSIER / "departements").glob("*.json"))}


@publies
def test_fichiers_entete_et_taille():
    fichiers = sorted(DOSSIER.rglob("*.json"))
    assert len(fichiers) > 100
    for f in fichiers:
        assert f.stat().st_size < 5_000_000, f.name
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["millesime"] and d["source"], f.name


@publies
def test_comptes_nationaux_coherents(index):
    c = dict(zip(index["colonnes"], index["totaux"]["comptes"]))
    assert c["etablissements"] == sum(c[d["id"]] for d in index["domaines"])
    assert sum(c[s["id"]] for s in index["secteurs"]) <= c["etablissements"]
    assert c["etablissements"] == sum(x["etablissements"] for x in index["categories"])
    assert c["etablissements"] == sum(x["etablissements"] for x in index["statuts_juridiques"])
    assert 50_000 < c["etablissements"] < 120_000 and 5_000 < c["ehpad"] < 9_000
    assert c["hospitalier"] > 5_000


@publies
def test_hors_perimetre_absent_des_nomenclatures_publiees(index):
    assert not [x for x in index["categories"] if x["categorie_agregee"] in se.AGREGATS_EXCLUS]
    assert "70" not in {x["code"] for x in index["statuts_juridiques"]}
    hp = index["confidentialite"]["hors_perimetre"]
    assert set(hp) == {"2103", "3101", "3201", "personne_physique"} and hp["3201"] > 10_000


@publies
def test_departements_somme_des_communes_et_total_national(index, par_dep):
    deps = charger("sante_etablissements/departements.json")
    n = len(index["colonnes"])
    total = [0] * n
    for dep, d in par_dep.items():
        assert d["departement"] == dep
        somme = [sum(li[2 + i] for li in d["communes"]["lignes"]) for i in range(n)]
        assert somme == deps["departements"][dep]["comptes"], dep
        assert all(se.departement(li[0]) == dep for li in d["communes"]["lignes"]), dep
        assert deps["departements"][dep]["fichier"] == f"sante_etablissements/departements/{dep}.json"
        total = [a + b for a, b in zip(total, somme)]
    nat = index["totaux"]["comptes"]
    assert all(t <= x for t, x in zip(total, nat)) and total[0] >= 0.995 * nat[0]
    assert {"44", "75", "2A", "971", "974"} <= set(par_dep)


@publies
def test_actes_ccam_departements_egale_national(index):
    deps = charger("sante_etablissements/departements.json")
    for i, an in enumerate(deps["annees_ccam"]):
        somme = sum(d["actes_ccam"][i] or 0 for d in deps["departements"].values())
        assert somme == index["totaux"]["actes_ccam"][str(an)], an
        assert 50_000_000 < somme < 120_000_000
    assert not set(deps["departements"]) & set(se.DEP_CCAM), "codes FINESS d'outre-mer non convertis"


@publies
def test_etablissements_listes_personnes_morales_sans_titre_ni_coordonnees(index, par_dep):
    cache = se.categories_juridiques()
    cats = {x["code"]: x for x in index["categories"]}
    interdits = re.compile(r"adresse|telephone|courriel|email|voie|postal|dirigeant|responsable|prenom|latitude|longitude")
    n = 0
    for dep, d in par_dep.items():
        cols = d["etablissements"]["colonnes"]
        assert not [c for c in cols + d["communes"]["colonnes"] if interdits.search(c)]
        ix = {c: i for i, c in enumerate(cols)}
        actes = [i for c, i in ix.items() if c.startswith("actes_ccam_")]
        prix = [i for c, i in ix.items() if c.endswith("_eur")]
        cles = []
        for li in d["etablissements"]["lignes"]:
            n += 1
            assert len(li) == len(cols)
            assert sirene.siren_valide(li[ix["siren"]]), li[0]
            assert not se.TITRE_PERSONNE.search(li[ix["nom"]]) and not se.TITRE_PERSONNE.search(li[ix["entite_juridique"]])
            assert se.departement(li[ix["commune"]]) == dep
            cat = cats[li[ix["categorie"]]]
            assert cat["categorie_agregee"] not in se.AGREGATS_EXCLUS
            assert (cat["domaine"] == "hospitalier" or li[ix["categorie"]] == se.CATEGORIE_EHPAD
                    or any(li[i] is not None for i in actes + prix)), li[0]
            if cache:
                assert sirene.personne_morale((cache.get(li[ix["siren"]]) or {}).get("cj")), li[0]
            cles.append((li[ix["commune"]], se.nom_tri(li[ix["nom"]]), li[0]))
        assert cles == sorted(cles), dep
        assert d["non_nommes"]["total"] == sum(d["non_nommes"]["par_motif"].values())
    assert n == index["totaux"]["etablissements_nommes"] > 1000
    assert set(index["confidentialite"]["non_nommes"]) <= set(se.MOTIFS)


@publies
def test_prix_ehpad_medianes_dans_les_bornes_et_presentes_comme_prix_payes(index):
    assert "pas une dépense publique" in index["note_prix"] and "résidents" in index["note_prix"]
    cols = index["colonnes_prix"]
    for an, bloc in index["totaux"]["prix_ehpad"].items():
        v = dict(zip(cols, bloc))
        assert 4_000 < v["ehpad_avec_prix"] < 9_000, an
        assert se.PRIX_MIN <= v["prix_hebergement_chambre_seule_median_eur"] <= 150
        assert v["tarif_dependance_gir_5_6_median_eur"] < v["tarif_dependance_gir_3_4_median_eur"] \
            < v["tarif_dependance_gir_1_2_median_eur"] <= se.TARIF_MAX
    assert "non précisée" in index["sources"]["cnsa_prix_ehpad"]["licence"]


@publies
def test_ecarts_recalculables_et_liens_vers_secu_et_subventions(index):
    assert len(index["ecarts"]) == 3
    for e in index["ecarts"]:
        assert e["nombre"] - e["autre_nombre"] == e["ecart"] and e["lecture_ecart"]
    vues = {li["vue"] for li in index["liens"]}
    assert "secu_arbre" in vues
    arbre = charger("secu/arbre/racine.json")

    def chercher(n, ident):
        if n.get("id") == ident:
            return n
        return next((r for x in n.get("enfants", []) if (r := chercher(x, ident))), None)
    for li in index["liens"]:
        assert (SITE / li["fichier"]).exists(), li["fichier"]
        if li["vue"] == "secu_arbre":
            assert chercher(arbre, li["id"])["md"] == li["md"]
    assert "robss/maladie/ondam_etablissements" in {li.get("id") for li in index["liens"]}
    if (SITE / "subventions" / "attribuants" / "subv_ars_pdl_fir.json").exists():
        assert "subventions" in vues
    assert "rien ne s'additionne" in index["regle_liens"]


@publies
def test_limites_disent_ce_qui_n_est_pas_ouvert():
    lim = charger("sante_etablissements/limites.json")
    sujets = " | ".join(x["sujet"] for x in lim["non_ouvert"])
    for attendu in ("Comptes par hôpital", "MIGAC", "Ségur", "Forfaits soins des EHPAD", "Fonds d'intervention"):
        assert attendu in sujets, attendu
    for x in lim["non_ouvert"]:
        assert x["etat"] and x["ce_qui_existe"]
        assert all((SITE / f).exists() for f in x["fichiers"]), x["sujet"]
    assert "pas l'usage de l'argent" in lim["avertissement"]
    rp = lim["recherche_publique"]
    assert rp["date"] and len(rp["trouvailles"]) >= 6 and rp["recherches_sans_resultat"]
    assert sum(x["nombre"] for x in lim["hors_perimetre"]["etablissements_actifs_exclus"].values()) > 20_000


@publies
def test_hospi_diag_historique_seulement():
    hd = charger("sante_etablissements/hospi_diag.json")
    ix = {c: i for i, c in enumerate(hd["colonnes"])}
    assert hd["annees"] == [2011, 2012, 2013, 2014, 2015] and "Historique" in hd["avertissement"]
    cles = [(li[ix["finess"]], li[ix["annee"]]) for li in hd["lignes"]]
    assert cles == sorted(cles) and len(set(cles)) == len(cles)
    for li in hd["lignes"]:
        assert 2011 <= li[ix["annee"]] <= 2015 and sirene.siren_valide(li[ix["siren"]])
        assert not se.TITRE_PERSONNE.search(li[ix["nom"]])
        assert li[ix["referentiel"]] in ("D", "O", None)
    assert set(hd["non_nommes"]["par_annee"]) == {str(a) for a in hd["annees"]}
    nb = {a: sum(1 for c in cles if c[1] == a) + sum(hd["non_nommes"]["par_annee"][str(a)].values()) for a in hd["annees"]}
    assert all(1_000 < n < 2_000 for n in nb.values()), nb


@publies
def test_finances_agregees_sans_etablissement_et_totaux():
    f = charger("sante_etablissements/finances_agregees.json")
    ix = {c: i for i, c in enumerate(f["colonnes"])}
    assert not {"finess", "siren", "nom"} & set(ix) and f["licence"] == "ODbL 1.0"
    for an, t in f["totaux"]["par_annee"].items():
        lignes = [li for li in f["lignes"] if li[ix["annee"]] == int(an)]
        for k, v in t.items():
            assert v == sum(li[ix[k]] or 0 for li in lignes), (an, k)
        assert 5e10 < t["produits_eur"] < 3e11


@publies
def test_production_identique_aux_fichiers_publies(tmp_path):
    """Sur l'entrepôt complet, une nouvelle production redonne les fichiers publiés, octet pour octet."""
    brut = ROOT / "data" / "lake" / "sante"
    attendus = ["sante_finess_structures", "sante_finess_ej_gel", "sante_finess_et_gel",
                "sante_open_ccam_etablissements", "sante_cnsa_prix_ehpad", "sante_hospi_diag"]
    if not all((brut / d).is_dir() and any((brut / d).iterdir()) for d in attendus) \
            or not (ROOT / "data" / "lake" / "secu" / "secu_atih_finances_ebnl.parquet").exists() \
            or not se.CJ_LOCAL.exists():
        pytest.skip("entrepôt data/lake/sante incomplet : reproductibilité non vérifiable ici")
    se.produire(tmp_path)
    publies_ = sorted(p.relative_to(DOSSIER) for p in DOSSIER.rglob("*.json"))
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.json")) == publies_
    differents = [str(p) for p in publies_ if (tmp_path / p).read_bytes() != (DOSSIER / p).read_bytes()]
    assert not differents, differents[:5]
