"""Aides aux entreprises (pipeline/aides_entreprises.py) : lecture du registre européen de transparence (TAM),
rattachements (secteur, région), confidentialité, écarts entre sources, cohérence des fichiers publiés.

Les tests unitaires et les tests sur site/data/aides_entreprises tournent sans réseau ni entrepôt ; la
reproductibilité demande l'entrepôt (data/lake/aides_entreprises/), sautée sinon.
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

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "aides_entreprises"
sys.path.insert(0, str(ROOT / "pipeline"))
import aides_entreprises as ae  # noqa: E402
import sirene  # noqa: E402

FICHIERS = ["index.json", "tam.json", "france2030.json", "france_relance.json", "pge.json"]
PRESENTS = all((DOSSIER / f).exists() for f in FICHIERS)
avec_donnees = pytest.mark.skipif(not PRESENTS, reason="site/data/aides_entreprises absent : lancer "
                                                        "`python pipeline/aides_entreprises.py produire`")


def charger(nom: str) -> dict:
    return json.loads((DOSSIER / nom).read_text(encoding="utf-8"))


# --- Lecture des pages du registre ----------------------------------------------------------------------------------

ENTETES = ["Pays", "Intitulé de la mesure d'aide", "Numéro SA", "Numéro de référence", "ID national",
           "Nom du bénéficiaire", "Type de bénéficiaire", "Région", "Secteur (NACE)", "Instrument d'aide",
           "Objectif de l’aide", "Montant nominal, exprimé en montant total",
           "Élément d'aide, exprimé en montant total", "Date d'octroi",
           "Nom de l'autorité chargée de l'octroi de l'aide", "Entité en charge", "Intermédiaires financiers",
           "Date de publication", "Benéficiaire dans un autre État membre", "Pays tiers hors UE"]


def page(lignes: list[list[str]], entetes=ENTETES, pagination: str = "") -> str:
    th = "".join(f"<th><a href='#'>{e}</a></th>" for e in entetes)
    corps = "".join("<tr>" + "".join(c for c in l) + "</tr>" for l in lignes)
    return (f"<html><body><table id='resultsTable'><thead><tr>{th}</tr></thead><tbody>{corps}</tbody></table>"
            f"{pagination}</body></html>")


LIGNE = ["<td>France</td>",
         "<td title=\"Régime cadre RDI 2014-2020 - plan d&#39;évaluation\" class='translatable'>Régime cadre RDI ..."
         "<span class='translationTooltip' title='R&amp;D'>en</span></td>",
         "<td class='small'><a href='x'>SA.40391</a></td>", "<td class='small'><a href='y'>TM-10000141</a></td>",
         "<td title='SIREN Number'> 531860823 </td>", "<td class='translatable'>MARIE DUPONT</td>",
         "<td>petites et moyennes entreprises</td>", "<td>Gironde</td>", "<td>Activités d&#39;ingénierie</td>",
         "<td>Subvention/Bonification d’intérêts</td>",
         "<td title='Recherche industrielle [art. 25, paragraphe 2, point b)]'>Recherche industrielle [art. ...</td>",
         "<td></td>", "<td title='1,406,726 EUR'>1,406,726 EUR</td>", "<td>28/07/2016</td>",
         "<td class='translatable'>Ministère de l&#39;économie et des finances "
         "<span class='translationTooltip' title='Ministry'>en</span></td>",
         "<td></td>", "<td></td>", "<td>15/09/2016</td>", "<td>France</td>", "<td></td>"]


def test_page_tam_lue_sans_le_nom_du_beneficiaire():
    lignes, dernier = ae.lire_page_tam(page([LIGNE], pagination="<a href='r?offset=200&amp;max=100'>3</a>"
                                                                "<a href='r?offset=100&amp;max=100'>2</a>"))
    assert dernier == 200
    assert len(lignes) == 1
    x = lignes[0]
    assert x["ref"] == "TM-10000141" and x["sa"] == "SA.40391"
    assert x["type_id"] == "SIREN Number" and x["id_national"] == "531860823"
    assert x["mesure"] == "Régime cadre RDI 2014-2020 - plan d'évaluation"   # texte complet de l'attribut title
    assert x["autorite"] == "Ministère de l'économie et des finances"      # infobulle de traduction retirée
    assert x["element_aide"] == "1,406,726 EUR" and x["montant_nominal"] is None
    assert "MARIE DUPONT" not in json.dumps(x, ensure_ascii=False)          # nom du bénéficiaire jamais lu
    assert set(x) - {"pays"} <= set(ae.TAM_CHAMPS)
    assert not set(ae.TAM_CHAMPS) & {"nom", "nom_beneficiaire", "beneficiaire", "denomination"}


def test_page_tam_colonne_inconnue_refusee():
    with pytest.raises(RuntimeError):
        ae.lire_page_tam(page([LIGNE], entetes=ENTETES[:-1] + ["Colonne nouvelle"]))


@pytest.mark.parametrize("valeur,attendu", [
    ("1,406,726 EUR", (1406726.0, 1406726.0, 1406726.0)),
    ("180,009.52 EUR", (180009.52, 180009.52, 180009.52)),
    ("500,001 à 1,000,000 EUR", (None, 500001.0, 1000000.0)),
    ("30,000,001 à EUR", (None, 30000001.0, None)),
    ("", (None, None, None)),
    ("non communiqué", (None, None, None)),
])
def test_montants_publies(valeur, attendu):
    assert ae.montant_tam(valeur) == attendu


def test_identifiants_et_tranches():
    assert ae.siren_de("43881012900025") == "438810129"
    assert ae.siren_de("842959249.0") == "842959249"
    assert ae.siren_de("12345") == "000012345"
    assert ae.siren_de("NR CHORUS") == "" and ae.siren_de("0") == "" and ae.siren_de(None) == ""
    assert ae.tranche(99_999.99) == "moins de 100 000 €"
    assert ae.tranche(100_000) == "de 100 000 € à moins de 500 000 €"
    assert ae.tranche(10_000_000) == "10 M€ et plus"


def test_nomenclatures_nace_2008_et_2025(tmp_path, monkeypatch):
    f = tmp_path / "secteurs.json"
    f.write_text(json.dumps({
        "a": {"value": "NACE Rev2 2008 - M.71.12 - Activités d'ingénierie"},
        "b": {"value": "NACE Rev2.1 2025 - N.71.12 - Activités d'ingénierie"},
        "c": {"value": "NACE Rev2.1 2025 - S - SECTION S — ARTS, SPORTS ET ACTIVITÉS RÉCRÉATIVES"},
        "d": {"value": "NACE Rev2.1 2025 - Q.85.40 - Enseignement tertiaire"},
        "e": {"value": "NACE Rev2 2008 - A - AGRICULTURE, SYLVICULTURE ET PÊCHE"},
    }), encoding="utf-8")
    monkeypatch.setattr(ae, "TAM_SECTEURS", f)
    n = ae.referentiel_nace()
    assert n[ae.sans_accents("Activités d’ingénierie")] == ("M", "71")
    assert n[ae.sans_accents("ARTS, SPORTS ET ACTIVITÉS RÉCRÉATIVES")] == ("R", None)
    assert n[ae.sans_accents("Enseignement tertiaire")] == ("P", "85")
    assert n[ae.sans_accents("Agriculture, sylviculture et pêche")] == ("A", None)
    assert set(ae.SECTION_DE_DIVISION.values()) == set(ae.SECTIONS_NAF)


@pytest.mark.skipif(not (SITE / "local" / "geo" / "44.json").exists(), reason="site/data/local/geo absent")
@pytest.mark.parametrize("libelle,attendu", [
    ("Ile-de-France", ("region", "11")), ("Île de France", ("region", "11")), ("Limousin", ("ancienne_region", "75")),
    ("Seine-et-Marne", ("departement", "11")), ("La Réunion", ("region", "04")), ("France", ("national", None)),
    ("Bassin Parisien", ("zone_pluriregionale", None)),
    ("RUP FR — Régions Ultrapériphériques Françaises", ("zone_pluriregionale", None)),
    ("Gelderland", ("non_rattache", None)), ("", ("non_rattache", None)),
])
def test_rattachement_des_lieux(libelle, attendu):
    assert ae.Territoires().region(libelle) == attendu


class IdentitesFactices(ae.Identites):
    def __init__(self, table):
        self.module, self.partage = table, {}


def test_groupe_conservation_et_personnes_physiques():
    ident = IdentitesFactices({"111111111": {"trouve": True, "cj": "5710", "nom": "SOCIETE A"},
                               "222222222": {"trouve": True, "cj": "1000"},
                               "333333333": {"trouve": True, "cj": "2110"}})
    g = ae.Groupe()
    for siren, m in (("111111111", 100.0), ("222222222", 50.0), ("333333333", 20.0), ("444444444", 7.0), ("", 3.0)):
        st, cj = ident.statut(siren) if siren else ("ni", None)
        g.ajouter(siren, st, cj, m, {2024: m})
    s = g.sortie(ident, top=1)
    assert [x["siren"] for x in s["top"]] == ["111111111"] and s["top"][0]["denomination"] == "SOCIETE A"
    assert s["exclus_personnes_physiques_ou_non_identifies"]["dont_personnes_physiques_eur"] == 70.0
    assert s["exclus_personnes_physiques_ou_non_identifies"]["dont_sans_siren_eur"] == 3.0
    assert s["autres_non_verifies"] == {"nombre": 1, "montant_eur": 7.0, "note": ae.NOTE_NON_VERIFIES}
    somme = (sum(x["montant_eur"] for x in s["top"]) + s["autres_personnes_morales"]["montant_eur"]
             + s["autres_non_verifies"]["montant_eur"] + s["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"])
    assert somme == s["total_eur"] == 180.0
    assert s["verification_classement"]["classement_complet"] is True   # 7 € non vérifiés < 100 € du dernier nommé


def test_aucun_texte_redige_ne_porte_un_jugement():
    lexique = json.loads((ROOT / "docs" / "lexique_neutre.json").read_text(encoding="utf-8"))
    regles = [re.compile(rf"(?<!\w)(?:{'|'.join(r['termes'])})(?!\w)", re.I) for r in lexique["regles"]]
    source = (ROOT / "pipeline" / "aides_entreprises.py").read_text(encoding="utf-8")
    for e in lexique["exceptions"]:
        source = source.replace(e, " ")
    textes = re.findall(r'"([^"\n]{25,})"', source)
    fautes = [t for t in textes for r in regles if r.search(t)]
    assert not fautes, fautes[:5]


# --- Fichiers publiés ------------------------------------------------------------------------------------------------

@avec_donnees
def test_fichiers_entetes_et_tailles():
    for f in FICHIERS:
        d = charger(f)
        assert d["millesime"] and d["source"], f
        assert (DOSSIER / f).stat().st_size < 5_000_000, f


def _somme(lst, cle="element_aide_eur"):
    return sum(x[cle] for x in lst)


@avec_donnees
def test_registre_ventilations_retombent_sur_le_total():
    t = charger("tam.json")
    total, aides = t["total"]["element_aide_eur"], t["total"]["aides"]
    sans_date = t.get("sans_date_octroi") or {"element_aide_eur": 0, "aides": 0}
    assert abs(sum(v["element_aide_eur"] for v in t["par_annee"].values()) + sans_date["element_aide_eur"] - total) < 1
    for cle in ("par_mesure", "par_objectif", "par_instrument", "par_type_beneficiaire", "par_secteur", "par_region",
                "par_tranche"):
        assert abs(_somme(t[cle]) - total) < 1, cle
        assert sum(x["aides"] for x in t[cle]) == aides, cle
    assert abs(sum(v["element_aide_eur"] for v in t["rattachement_regions"].values()) - total) < 1
    for an, v in t["par_annee"].items():
        for croisement in ("annee_secteur", "annee_region", "annee_tranche"):
            c = t["croisements"][croisement][an]
            assert abs(sum(x["element_aide_eur"] for x in c.values()) - v["element_aide_eur"]) < 1, (croisement, an)
    for s in t["par_secteur"]:
        assert sum(d["element_aide_eur"] for d in s["divisions"]) <= s["element_aide_eur"] + 1


@avec_donnees
def test_registre_fourchettes_jamais_ajoutees_au_montant():
    t = charger("tam.json")
    for x in t["par_tranche"]:
        if x["tranche"] in ("fourchette publiée", "montant non publié"):
            assert x["element_aide_eur"] == 0 and x["aides_avec_montant"] == 0


@avec_donnees
def test_registre_beneficiaires_personnes_morales_seulement():
    b = charger("tam.json")["beneficiaires"]
    assert len(b["top"]) <= 50
    for x in b["top"]:
        assert sirene.personne_morale(x["categorie_juridique"]), x
        assert re.fullmatch(r"[0-9]{9}", x["siren"]) and x["denomination"]
        assert abs(sum(x["par_annee_eur"].values()) - x["montant_eur"]) < 1
    montants = [x["montant_eur"] for x in b["top"]]
    assert montants == sorted(montants, reverse=True)
    v = b["verification_classement"]
    assert v["classement_complet"] == (v["non_verifies_au_dessus_du_seuil"] == 0)


@avec_donnees
def test_relance_laureats_nommes_sont_des_personnes_morales():
    r = charger("france_relance.json")["laureats"]
    assert r["colonnes"][:3] == ["siren", "denomination", "categorie_juridique"]
    for l in r["lignes"]:
        assert sirene.personne_morale(l[2]) and l[1], l
    assert r["projets_nommes"] == len(r["lignes"])
    assert r["projets_nommes"] + sum(r["projets_agreges"].values()) == r["projets_publies"]


@avec_donnees
def test_relance_montants_et_ecarts():
    r = charger("france_relance.json")
    m = r["montants"]
    assert abs(sum(v["participation_etat_eur"] for v in m["par_mesure"].values())
               - m["totaux_participation_etat_eur"]["mesure_filiere"]) < 1
    assert abs(_somme(m["par_region"], "participation_etat_eur")
               - m["totaux_participation_etat_eur"]["region_departement"]) < 1
    for e in r["ecarts"]:
        assert abs(e["montant_eur"] - e["autre_montant_eur"] - e["ecart_eur"]) < 0.02, e
        assert e["lecture_ecart"]


@avec_donnees
def test_france2030_ventilations_et_rapprochement():
    f = charger("france2030.json")
    total = f["total"]["montant_eur"]
    assert abs(sum(v["montant_eur"] for v in f["par_annee"].values()) - total) < 1
    for cle in ("par_operateur", "par_region_financement", "par_region_beneficiaire", "par_secteur", "par_typologie",
                "par_objectif", "par_strategie", "par_programme"):
        assert abs(_somme(f[cle], "montant_eur") - total) < 1, cle
        assert sum(x["projets"] for x in f[cle]) == f["total"]["projets"], cle
    if f["rapprochement"]:
        assert abs(f["rapprochement"]["ecart_eur"]) < 1
    assert "top" not in json.dumps(f)   # bénéficiaires nommés : beneficiaires/france2030.json seulement


@avec_donnees
def test_pge_situations_et_annees():
    p = charger("pge.json")
    dernier = p["dates"][-1]
    for cle in ("par_secteur", "par_region", "par_departement"):
        for d in p["dates"]:
            assert abs(sum(x["situations"][d]["montant_eur"] for x in p[cle] if d in x["situations"])
                       - p["total"]["situations"][d]["montant_eur"]) < 1, (cle, d)
    if p.get("methode_par_annee"):
        pa = p["total"]["par_annee"]
        assert abs(pa["2020"]["montant_eur"] + pa["2021"]["montant_eur"]
                   - p["total"]["situations"][dernier]["montant_eur"]) < 1
    for e in p["ecarts"]:
        assert abs(e["montant_eur"] - e["autre_montant_eur"] - e["ecart_eur"]) < 0.02, e


@avec_donnees
def test_index_sources_cote_a_cote_jamais_additionnees():
    i = charger("index.json")
    ids = [d["id"] for d in i["dispositifs"]]
    assert len(ids) == len(set(ids)) and {"tam", "france2030", "france_relance_industrie", "pge"} <= set(ids)
    par_id = {d["id"]: d for d in i["dispositifs"]}
    for an, v in i["par_annee"]["annees"].items():
        for src, m in v.items():
            assert m == par_id[src]["par_annee_eur"][an], (an, src)
    assert not re.search(r'"total_(?:toutes_sources|general|ensemble)', json.dumps(i))
    for e in i["ecarts"]:
        assert e["lecture_ecart"] and abs(e["montant_eur"] - e["autre_montant_eur"] - e["ecart_eur"]) < 0.02, e
    for l in i["liens"]:
        assert (SITE / l["fichier"]).exists(), l
    assert any(l["fichier"] == "prestations/index.json" for l in i["liens"]) == (SITE / "prestations"
                                                                                 / "index.json").exists()


@avec_donnees
def test_recherche_publique_classee():
    r = charger("index.json")["recherche_publique"]
    assert len(r["trouvailles"]) >= 5
    for t in r["trouvailles"]:
        assert re.match(r"(réutilisable tel quel|à adapter|inspiration seulement|aucun autre dépôt)", t["verdict"]), t
        assert t["licence"] and t["mise_a_jour"] and t["url"].startswith("https://")


# --- Reproductibilité (entrepôt requis) ----------------------------------------------------------------------------

@pytest.mark.skipif(not any(ae.TAM_DIR.glob("fr_*.csv")) or not ae.SOURCES["france2030"]["chemin"].exists(),
                    reason="entrepôt data/lake/aides_entreprises absent : reproductibilité non vérifiable ici")
def test_production_reproductible(tmp_path):
    empreintes = []
    for graine in ("1", "2"):
        sortie = tmp_path / graine
        env = {**os.environ, "PYTHONHASHSEED": graine}
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "aides_entreprises.py"), "produire", "--sortie",
                        str(sortie)], check=True, env=env, capture_output=True, cwd=ROOT)
        empreintes.append({f: hashlib.sha256((sortie / f).read_bytes()).hexdigest() for f in FICHIERS})
    assert empreintes[0] == empreintes[1]
