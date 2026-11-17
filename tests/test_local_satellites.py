"""Satellites locaux (pipeline/local_satellites.py) : fonctions de lecture et de rattachement, puis cohérence des
fichiers publiés. Sans réseau ni entrepôt brut."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "local_satellites"
sys.path.insert(0, str(ROOT / "pipeline"))
import local_satellites as ls  # noqa: E402

INTERDITS = {"courriel", "email", "mail", "adresse", "telephone", "president", "dirigeant", "responsable", "operateur",
             "nom_operateur", "prenom"}


# --- Fonctions (sans fichier publié) ---------------------------------------------------------------------------------

def test_nombre_jamais_zero_a_la_place_d_une_absence():
    assert ls.nombre("") is None and ls.nombre(None) is None and ls.nombre("nc") is None
    assert ls.nombre("0,55") == 0.55 and ls.nombre("1 234,5") == 1234.5 and ls.nombre(0) == 0
    assert ls.entier("") is None and ls.entier("77303.0") == 77303
    assert ls.par_habitant(100, 0) is None and ls.par_habitant(None, 10) is None and ls.par_habitant(100, 3) == 33.33


def test_arrondi_en_centimes_independant_de_l_ordre():
    assert ls.arrondi_centimes(150) == 2 and ls.arrondi_centimes(149) == 1 and ls.arrondi_centimes(-150) == -2
    assert ls.arrondi_centimes(0) == 0 and ls.arrondi_centimes(5985677) == 59857


def test_arrondissements_ramenes_a_la_commune():
    assert ls.commune_de("75112") == "75056" and ls.commune_de("69382") == "69123" and ls.commune_de("13203") == "13055"
    assert ls.commune_de("1004") == "01004" and ls.commune_de("44066") == "44066"


def test_taux_en_vigueur_a_la_date_de_reference():
    p = [("20040101", "20041231", 1.55, None, None), ("20230701", "", 2.0, 0.1, None), ("20260701", "", 2.2, 0.1, 0.15)]
    cours, suivant = ls.taux_en_vigueur(p, "20260101")
    assert cours[0] == "20230701" and cours[2] == 2.0 and suivant[0] == "20260701" and suivant[4] == 0.15
    assert ls.taux_en_vigueur([("20040101", "20041231", 1.55, None, None)], "20260101") == (None, None)
    assert ls.taux_en_vigueur([], "20260101") == (None, None)


def test_dernier_montant_limite_aux_deux_derniers_exercices():
    assert ls.dernier_montant([1, 2, 3, 4, 5, 6, 7, 8]) == (2025, 8)
    assert ls.dernier_montant([1, 2, 3, 4, 5, 6, 7, None]) == (2024, 7)
    assert ls.dernier_montant([1, 2, 3, 4, 5, 6, None, None]) == (None, None)


def test_rattachement_direct_par_epci_et_par_syndicat():
    g = {"communes": {"01001": {"siren": "210100012", "epci": "200000001"},
                      "01002": {"siren": "210100020", "epci": "200000002"}}}
    banatic = {"groupements": {
        "250000001": {"nature": "SIVU", "membres": [("210100012", "commune")]},
        "250000002": {"nature": "SMF", "membres": [("200000001", "groupement"), ("210100012", "commune")]},
        "250000003": {"nature": "SMO", "membres": [("250000001", "groupement"), ("220100010", "personne morale")]},
        "250000004": {"nature": "SMO", "membres": [("220100010", "personne morale")]},
        "200000001": {"nature": "CC", "membres": [("210100012", "commune")]}}}
    par_commune, communes_de = ls.rattacher_syndicats(banatic, g)
    assert par_commune["01001"] == {"250000001": "commune", "250000002": "commune", "250000003": "syndicat"}
    assert "01002" not in par_commune and "200000001" not in communes_de and "250000004" not in communes_de


def test_lecture_en_flux_et_liste_blanche_banatic(tmp_path):
    entete = ["Département", "N° SIREN", "Nom du groupement", "Nature juridique", "Syndicat à la carte",
              "Courriel du siège", "Nom Président", "Population totale", "Nombre de membres", "Siren membre",
              "Catégorie des membres du groupement", ls.BANATIC_PREMIERE_COMPETENCE, "Eclairage public", "Autres"]
    lignes = [entete,
              ["01 - Ain", "250000001", "SI des eaux &amp; test", "SIVU", "NON", "a@b.fr", "DUPONT", "1150", "2",
               "210100012", "commune", "NON", "OUI", "NON"],
              ["01 - Ain", "250000001", "SI des eaux &amp; test", "SIVU", "NON", "a@b.fr", "DUPONT", "1150", "2",
               "210100020", "commune", "NON", "OUI", "NON"]]

    def ref(i):
        return chr(65 + i)

    xml = "<worksheet><sheetData>" + "".join(
        f'<row r="{n + 1}">' + "".join(
            f'<c r="{ref(i)}{n + 1}" s="0" t="inlineStr"><is><t>{v}</t></is></c>' for i, v in enumerate(l) if i != 4)
        + "</row>" for n, l in enumerate(lignes)) + "</sheetData></worksheet>"
    xml = xml.replace('<row r="1">', '<row r="1"><c r="E1" s="0" t="inlineStr"><is><t>Syndicat à la carte</t></is></c>', 1)
    f = tmp_path / "b.xlsx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", xml)
    x = ls.extraire_banatic(f)
    assert x["competences"] == [ls.BANATIC_PREMIERE_COMPETENCE, "Eclairage public", "Autres"]
    gr = x["groupements"]["250000001"]
    assert gr["nom"] == "SI des eaux & test" and gr["population"] == 1150 and gr["competences"] == [1]
    assert gr["a_la_carte"] is False  # cellule absente : colonnes repérées par leur référence, sans décalage
    assert [m[0] for m in gr["membres"]] == ["210100012", "210100020"]
    assert "DUPONT" not in json.dumps(x) and "a@b.fr" not in json.dumps(x)


def test_agregats_et_sources_declares():
    assert set(ls.AGREGATS_SYNDICATS) >= {"depenses_totales_hors_remb", "subventions_participations_recues"}
    assert "participations_communes" in ls.AGREGATS_CCAS
    for cle in ("cerema_aom", "urssaf_vm"):
        assert ls.SOURCES[cle]["licence"] == "ODbL 1.0"
    for t in ls.RECHERCHE_PUBLIQUE["trouvailles"]:
        assert t["classement"] in ("réutilisable tel quel", "à adapter", "inspiration seulement") and t["licence"]
    assert {f["id"] for f in ls.FLUX_CROISES} >= {"contributions_aux_syndicats", "subvention_au_ccas",
                                                  "aom_deja_publiee", "services_d_eau"}


# --- Fichiers publiés ------------------------------------------------------------------------------------------------

publies = pytest.mark.skipif(not (DOSSIER / "index.json").exists(),
                             reason="site/data/local_satellites absent : lancer `python pipeline/local_satellites.py`")
DEPS_TEST = ["01", "2A", "44", "59", "75", "971"]


def charger(rel):
    return json.loads((DOSSIER / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return charger("index.json")


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


@publies
def test_toutes_les_communes_du_referentiel_et_masques_coherents(index):
    geo = set()
    for f in (SITE / "local" / "geo").glob("*.json"):
        geo |= set(json.loads(f.read_text(encoding="utf-8"))["communes"])
    assert set(index["communes"]) == geo
    assert index["couverture"]["communes"] == len(geo)
    blocs = index["blocs"]
    for i, b in enumerate(blocs):
        assert index["couverture"]["par_bloc"][b] == sum(1 for m in index["communes"].values() if m >> i & 1)
    for dep in DEPS_TEST:
        s, c, m, e = (charger(f"{d}/{dep}.json") for d in ("syndicats", "ccas", "mobilite", "eau"))
        for code, masque in index["communes"].items():
            if ls.code_dep(code) != dep:
                continue
            assert bool(masque >> blocs.index("syndicats") & 1) == bool(s["communes"].get(code)), code
            types = {c["centres"][x]["type"] for x in c["communes"].get(code, [])}
            assert bool(masque >> blocs.index("ccas") & 1) == ("ccas" in types), code
            assert bool(masque >> blocs.index("cias") & 1) == ("cias" in types), code
            ligne = m["communes"].get(code)
            assert bool(masque >> blocs.index("aom") & 1) == bool(ligne and ligne[0]), code
            assert bool(masque >> blocs.index("versement_mobilite") & 1) == bool(ligne and ligne[4]), code
            comp = {e["services"][i][0] for cle, _ in e["communes"].get(code, []) for i in e["collectivites"][cle]["services"]}
            for b in ("eau_potable", "assainissement_collectif", "assainissement_non_collectif"):
                assert bool(masque >> blocs.index(b) & 1) == (b in comp), (code, b)


@publies
def test_un_fichier_par_departement_et_par_bloc_sous_5_mo(index):
    for d in ("syndicats", "ccas", "mobilite", "eau"):
        fichiers = sorted(p.stem for p in (DOSSIER / d).glob("*.json"))
        assert fichiers == sorted(index["departements"]), d
        assert max(p.stat().st_size for p in (DOSSIER / d).glob("*.json")) < 5_000_000


@publies
def test_syndicats_references_depenses_et_montant_par_habitant(index):
    for dep in DEPS_TEST:
        d = charger(f"syndicats/{dep}.json")
        cites = {s for l in d["communes"].values() for s, _ in l} | set(d["organismes_departementaux"]) \
            | {s for s, _ in d["non_rattaches"]}
        assert cites == set(d["syndicats"]), dep
        for s, f in d["syndicats"].items():
            assert f["comptes"] == (f["serie"] is not None), s
            assert all(0 <= i < len(index["competences"]) for i in f["competences"] or []), s
            if not f["serie"]:
                assert f["eur_hab"] is None
                continue
            for i in range(len(d["annees"])):
                t, fo, inv = (f["serie"][k][i] for k in ("depenses_totales_hors_remb", "depenses_fonctionnement",
                                                         "depenses_investissement_hors_remb"))
                if None not in (t, fo, inv):
                    assert abs(t - fo - inv) <= 2, (s, d["annees"][i])
            if f["eur_hab"] is not None:
                m = f["serie"]["depenses_totales_hors_remb"][d["annees"].index(f["eur_hab_exercice"])]
                assert f["eur_hab"] == round(m / f["population"], 2), s
        for code, l in d["communes"].items():
            assert l == sorted(l) and len({s for s, _ in l}) == len(l), code


@publies
def test_totaux_non_consolides_recalculables(index):
    """Somme, sans doublon, des organismes des fichiers départementaux et de `hors_departement` = total de l'index."""
    vus = dict(index["hors_departement"]["syndicats"])
    centres = dict(index["hors_departement"]["ccas"])
    for dep in index["departements"]:
        vus.update(charger(f"syndicats/{dep}.json")["syndicats"])
        centres.update(charger(f"ccas/{dep}.json")["centres"])
    dernier = len(index["annees"]) - 1
    for cat, t in index["totaux"]["syndicats"].items():
        somme = sum(f["serie"]["depenses_totales_hors_remb"][dernier] or 0 for f in vus.values()
                    if f["serie"] and f["categorie"] == cat)
        assert somme == t["depenses_totales_hors_remb"][dernier], cat
    for typ, t in index["totaux"]["ccas_cias"].items():
        for cle in ("depenses_totales_hors_remb", "participations_communes"):
            somme = sum(f["serie"][cle][dernier] or 0 for f in centres.values() if f["type"] == typ)
            assert somme == t[cle][dernier], (typ, cle)
    assert "non consolidées" in index["totaux"]["note"]
    r = index["reperes"]
    assert 0 < r["ccas_part_participations_communes_pct"] < 100
    assert r["syndicats_avec_comptes"] > 5000 and r["ccas_avec_comptes"] > 5000


@publies
def test_ccas_rattachement_et_population():
    geo = json.loads((SITE / "local" / "geo" / "44.json").read_text(encoding="utf-8"))
    d = charger("ccas/44.json")
    for code, l in d["communes"].items():
        for s in l:
            f = d["centres"][s]
            if f["type"] == "ccas":
                assert f["commune_siege"] == code and f["rattachement"] == "commune_siege"
                assert f["population"] == geo["communes"][code]["population"]
            else:
                assert f["rattachement"] == "epci_de_la_commune_siege" and f["epci"] == geo["communes"][code]["epci"]
                assert isinstance(f["competence_cias_banatic"], bool)
    for s in d["non_rattaches"]:
        assert d["centres"][s]["rattachement"] is None and d["centres"][s]["eur_hab"] is None
    paris = charger("ccas/75.json")
    assert paris["communes"]["75056"] and paris["non_rattaches"] == []


@publies
def test_mobilite_odbl_taux_et_liens_sans_montant_recopie(index):
    assert index["licences"]["mobilite"]["licence"] == "ODbL 1.0"
    assert any(s["id"] == "urssaf_vm" and s["licence"] == "ODbL 1.0" for s in index["sources"])
    for dep in DEPS_TEST:
        d = charger(f"mobilite/{dep}.json")
        assert d["licence"] == "ODbL 1.0" and "partage" in d["partage_a_l_identique"] and "Urssaf" in d["mention"]
        for code, l in d["communes"].items():
            aom, vm, vma, vmr, debut, sru, suivant = l
            assert aom is None or aom in d["aom"], code
            assert (debut is None) == (vm is None and vma is None and vmr is None), code
            assert debut is None or debut <= "20260101", code
            assert sru is None or 0 <= sru < len(d["syndicats_sru"])
            assert suivant is None or suivant[0] > "20260101"
        for s, a in d["aom"].items():
            if a["comptes"]:
                assert (SITE / a["comptes"]["fichier"]).exists(), s
                assert set(a["comptes"]) == {"vue", "fichier"}  # un lien, jamais un montant
    paris = charger("mobilite/75.json")
    assert paris["communes"]["75056"][1] is not None and paris["aom"]["287500078"]["comptes"] is None
    e = index["ecarts"]["versement_mobilite_urssaf_cerema"]
    assert e["communes_comparees"] > 5000 and 0 <= e["ecarts"] < e["communes_comparees"] and e["lecture_ecart"]


@publies
def test_eau_prix_modes_de_gestion_et_rattachement(index):
    prix = []
    for dep in DEPS_TEST:
        d = charger(f"eau/{dep}.json")
        i_prix, i_mode, i_comp = (d["colonnes"].index(k) for k in ("prix_m3_ttc", "mode_gestion", "competence"))
        services_cites = [i for c in d["collectivites"].values() for i in c["services"]]
        assert sorted(services_cites) == sorted(d["services"]), dep
        for ident, l in d["services"].items():
            assert ident.startswith({"eau_potable": "AEP", "assainissement_collectif": "AC",
                                     "assainissement_non_collectif": "ANC"}[l[i_comp]])
            if l[i_comp] == "assainissement_non_collectif":
                assert l[i_prix] is None
            elif l[i_prix] is not None:
                prix.append(l[i_prix])
            assert l[i_mode] in ("Régie", "Délégation", "Inconnu", None), ident
        for code, l in d["communes"].items():
            assert all(cle in d["collectivites"] for cle, _ in l), code
        for cle in d["non_rattaches"]:
            assert cle in d["collectivites"]
        for c in d["collectivites"].values():
            if c["comptes"]:
                assert (SITE / c["comptes"]["fichier"]).exists()
    prix.sort()
    assert 1 < prix[len(prix) // 2] < 4  # médiane des prix TTC au m³ publiés : ordre de grandeur
    b = index["reperes"]["services_eau"]
    assert b["eau_potable"]["avec_prix"] < b["eau_potable"]["entites"]  # prix non saisis : null, jamais 0
    assert b["assainissement_non_collectif"]["avec_prix"] is None


@publies
def test_confidentialite_aucune_colonne_personnelle(index):
    assert not INTERDITS & set(_cles(index))
    for dep in DEPS_TEST:
        for d in ("syndicats", "ccas", "mobilite", "eau"):
            doc = charger(f"{d}/{dep}.json")
            assert not INTERDITS & set(_cles(doc)), (d, dep)
            texte = json.dumps(doc, ensure_ascii=False)
            assert "@" not in texte, (d, dep)
    assert index["non_nommes"]["regle"] and "opérateur" in index["non_nommes"]["operateurs_eau"]
    assert any("410" in s["constat"] for s in index["sources_inaccessibles"])


@publies
def test_flux_croises_documentes_et_fichiers_cites_presents(index):
    ids = [f["id"] for f in index["flux_croises"]]
    assert ids == [f["id"] for f in ls.FLUX_CROISES] and len(set(ids)) == len(ids)
    for f in index["flux_croises"]:
        assert f["regle"] and f["deja_publie"] and f["ici"]
    for dossier in ("local/budgets/communes", "local/budgets/epci"):
        assert (SITE / dossier).is_dir()
    assert (SITE / "local" / "budgets" / "regions.json").exists()
