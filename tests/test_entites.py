"""Organisations reliées d'une source à l'autre (pipeline/entites.py) : fichiers publiés et fonctions, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
DOSSIER = SITE / "entites"
sys.path.insert(0, str(ROOT / "pipeline"))
import entites  # noqa: E402
import sirene  # noqa: E402


# --- Fonctions (jeu synthétique) -------------------------------------------------------------------------------------

def test_siren_et_siret():
    assert entites.siren_de("130 006 372") == "130006372"
    assert entites.siren_de("13000637200017") == "130006372"
    assert entites.siren_de("NR CHORUS") is None and entites.siren_de(None) is None and entites.siren_de("12345") is None


def test_normalisation_des_noms():
    assert entites.normaliser("Centre hospitalier d'Angoulême") == entites.normaliser("CENTRE HOSPITALIER D ANGOULEME")
    assert entites.normaliser("Conseil départemental de la Vendée") == entites.normaliser("DEPARTEMENT DE LA VENDEE")
    assert entites.normaliser("Syndicat X (SIX)") == "SYNDICAT X"
    assert entites.periode_de([2021, 2026, 2023]) == "2021-2026" and entites.periode_de([2024]) == "2024"


def _app(canal, notion, annee, montant, groupe=None, periode=None, precision="p"):
    return entites.A("130006372", "X", "7389", canal, notion, "f/x.json", annee=annee, periode=periode, montant=montant,
                     precision=precision, groupe=groupe)


def test_sommes_regle_13_meme_canal_meme_annee_meme_groupe():
    apps = [_app("associations_jaunes", "credits_etat_verses", 2023, 100.0, precision="programme 101"),
            _app("associations_jaunes", "credits_etat_verses", 2023, 50.0, precision="programme 102"),
            _app("associations_jaunes", "credits_etat_verses", 2022, 70.0, precision="programme 101"),
            # notion non additionnable dans le canal, même année : jamais de somme
            _app("aides_registre_europeen", "element_aide", 2023, 10.0),
            _app("aides_registre_europeen", "element_aide", 2023, 20.0, precision="q"),
            # période : jamais additionnée
            _app("subventions", "subvention_attribuee", None, 5.0, periode="2021-2026")]
    blocs = {b["canal"]: b for b in entites.blocs_de(apps)}
    assert blocs["associations_jaunes"]["sommes_par_annee"] == [[2023, 150.0, 2]]
    assert "sommes_par_annee" not in blocs["aides_registre_europeen"]
    assert "sommes_par_annee" not in blocs["subventions"]
    assert entites.sommes_entre_canaux(list(blocs.values())) == []


def test_sommes_par_groupe_jamais_melangees():
    apps = [_app("hospi_diag", "recettes_t2a_declarees", 2012, 1.0, groupe="référentiel D", precision="a"),
            _app("hospi_diag", "recettes_t2a_declarees", 2012, 2.0, groupe="référentiel D", precision="b"),
            _app("hospi_diag", "recettes_t2a_declarees", 2012, 4.0, groupe="référentiel O", precision="c")]
    (b,) = entites.blocs_de(apps)
    assert b["sommes_par_annee"] == [[2012, 3.0, 2, "référentiel D"]]


def test_aucune_notion_cumulable_entre_canaux_sans_decision():
    # Ajouter une notion cumulable entre canaux est une décision documentée : ce test le rappelle.
    assert all(n["cumulable"] is None for n in entites.NOTIONS.values())
    assert {n["sens"] for n in entites.NOTIONS.values()} == {"recoit", "verse", "mention"}


def test_rapprochement_splink_probable_seulement_si_nom_identique():
    pytest.importorskip("splink")
    g = [{"id": "g1", "nom_norm": entites.normaliser("Centre hospitalier de Cambrai"), "departement": "59"},
         {"id": "g2", "nom_norm": entites.normaliser("Syndicat des eaux du Nord"), "departement": "59"},
         {"id": "g3", "nom_norm": entites.normaliser("Centre hospitalier de Cambrai"), "departement": "62"}]
    d = [{"id": "260590098|59", "nom_norm": entites.normaliser("CENTRE HOSPITALIER DE CAMBRAI"), "departement": "59"},
         {"id": "200000000|59", "nom_norm": entites.normaliser("COMMUNE DE CAMBRAI"), "departement": "59"}]
    p = entites.rapprocher(g, d)
    forts = [x for x in p if x["probabilite"] >= entites.SEUIL_PROBABLE]
    assert [(x["cle_g"], x["cle_d"]) for x in forts] == [("g1", "260590098|59")]
    assert not [x for x in p if x["cle_g"] == "g3"]  # autre département : jamais comparé


def test_rapprochement_national_par_premier_mot_jamais_avec_un_departement():
    pytest.importorskip("splink")
    nn = entites.normaliser
    g = [{"id": "n1", "nom_norm": nn("SOCIETE EDITRICE DU MONDE"), "departement": None,
          "bloc": "mot:" + nn("SOCIETE EDITRICE DU MONDE").split()[0]},
         {"id": "n2", "nom_norm": nn("SIPA"), "departement": None, "bloc": "mot:SIPA"},
         {"id": "d1", "nom_norm": nn("SIPA"), "departement": "35"}]
    d = [{"id": "433891850|*", "nom_norm": nn("SOCIETE EDITRICE DU MONDE"), "departement": None,
          "bloc": "mot:SOCIETE"},
         {"id": "111111111|*", "nom_norm": nn("SIPA"), "departement": None, "bloc": "mot:SIPA"},
         {"id": "222222222|75", "nom_norm": nn("SOCIETE EDITRICE DU MONDE"), "departement": "75"}]
    p = entites.rapprocher(g, d)
    paires = {(x["cle_g"], x["cle_d"]) for x in p if x["probabilite"] >= entites.SEUIL_PROBABLE}
    assert paires == {("n1", "433891850|*"), ("n2", "111111111|*")}
    # un sigle d'un seul mot n'est jamais retenu comme probable pour une source nationale (règle de produire)
    assert len(g[1]["nom_norm"].split()) < entites.MOTS_MIN_NATIONAL
    assert not [x for x in p if x["cle_g"] == "d1"]  # ligne avec département : jamais comparée au blocage national


def test_nouvelles_sources_decrites():
    for c in ("fonds_vert", "dotations_investissement", "deliberations", "presse_groupes", "ditp_itn7"):
        assert c in entites.CANAUX
        assert entites.CANAUX[c]["page"] in entites.ROUTES_CONNUES | {None}
    assert entites.NOTIONS["deliberations_publiees"]["sens"] == "mention"
    relus = " ".join(x["chemins_source"] for x in entites.NON_RELUS)
    for chemin in ("subv_fonds_vert", "sport/federations.json", "agriculture/", "performance/"):
        assert chemin in relus


# --- Fichiers publiés --------------------------------------------------------------------------------------------

if not (DOSSIER / "index.json").exists():
    pytest.skip("site/data/entites absent : lancer `python pipeline/entites.py produire`", allow_module_level=True)

INDEX = json.loads((DOSSIER / "index.json").read_text(encoding="utf-8"))
FICHES = {}
for _p in sorted((DOSSIER / "fiches").glob("*.json")):
    FICHES.update(json.loads(_p.read_text(encoding="utf-8"))["fiches"])


def test_index_canaux_et_notions():
    assert [c["id"] for c in INDEX["canaux"]] == list(entites.CANAUX)
    assert set(INDEX["notions"]) == set(entites.NOTIONS)
    for c in INDEX["canaux"]:
        assert set(c["notions"]) <= set(INDEX["notions"]), c["id"]
        assert c["organisations_avec_fiche"] <= c["organisations"]
    assert INDEX["comptes"]["organisations_avec_fiche"] == len(FICHES)
    v = {t["verdict"] for t in INDEX["recherche_publique"]["trouvailles"]}
    assert v <= {"réutilisable tel quel", "à adapter", "inspiration seulement"}


def test_tailles_et_entetes():
    for p in DOSSIER.rglob("*.json"):
        assert p.stat().st_size < 1_000_000, p
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d.get("millesime") and d.get("source"), p


def test_personnes_morales_seulement():
    from local import contient_nom_de_personne, prenoms
    liste = prenoms()
    for s, f in FICHES.items():
        assert sirene.personne_morale(f["categorie_juridique"]), s
        assert not contient_nom_de_personne(f["denomination"], liste), s
        assert f["siren"] == s


def test_une_fiche_relie_au_moins_deux_canaux():
    for s, f in FICHES.items():
        canaux = {b["canal"] for b in f["recoit"] + f["autres"]}
        assert canaux == set(f["canaux"]), s
        assert len(canaux) >= 2 or f.get("probables"), s
        assert all(entites.NOTIONS[b["notion"]]["sens"] == "recoit" for b in f["recoit"]), s
        assert all(entites.NOTIONS[b["notion"]]["sens"] != "recoit" for b in f["autres"]), s


def test_sommes_publiees_recalculees():
    for s, f in FICHES.items():
        assert not f.get("sommes_entre_canaux"), s  # aucune notion cumulable entre canaux
        for b in f["recoit"] + f["autres"]:
            if "sommes_par_annee" not in b:
                continue
            assert entites.NOTIONS[b["notion"]]["somme_canal"], (s, b["notion"])
            if b.get("series_non_affichees") or any(len(x) == 4 for x in b["sommes_par_annee"]):
                continue
            for an, somme, n in b["sommes_par_annee"]:
                vals = [v[1] for x in b["series"] for v in x["valeurs"] if v[0] == an and v[1] is not None]
                assert len(vals) == n and abs(sum(vals) - somme) < 0.05, (s, b["canal"], an)


def test_rapprochements_probables_a_part():
    dec = INDEX["comptes"]["lignes_sans_siren"]
    assert sum(dec["decisions"].values()) == dec["total"]
    n = 0
    for s, f in FICHES.items():
        for p in f.get("probables", []):
            n += 1
            assert p["score"] >= entites.SEUIL_PROBABLE and p["decision"] == "probable", s
    assert n == dec["decisions"].get("probable", 0)


def test_recherche_retrouve_chaque_fiche():
    cles = INDEX["fichiers"]["recherche"]
    frequents = {m["mot"] for m in INDEX["fichiers"]["mots_frequents"]}
    contenus = {}

    def fichier_de(mot):
        k = mot + "_" if mot + "_" in cles else max((c for c in cles if not c.endswith("_") and mot.startswith(c)),
                                                    key=len, default=None)
        return cles.get(k) if k else None

    for s, f in sorted(FICHES.items())[::97]:  # échantillon régulier
        mots = [m for m in entites.mots_recherche(f["denomination"]) if len(m) >= 2 and m.upper() not in entites.MOTS_VIDES
                and m not in frequents]
        if not mots:  # nom sans mot de deux lettres (« E.M.A ») : fiche trouvée par son SIREN
            assert not [m for m in entites.mots_recherche(f["denomination"]) if len(m) >= 2], s
            continue
        rel = fichier_de(mots[0])
        assert rel, (s, mots[0])
        if rel not in contenus:
            contenus[rel] = {e[0] for e in json.loads((SITE / rel).read_text(encoding="utf-8"))["entrees"]}
        assert s in contenus[rel], (s, rel)
    # chaque fiche se retrouve par son préfixe de SIREN
    pref = INDEX["fichiers"]["fiches"]
    for s in list(FICHES)[::211]:
        k = max((p for p in pref if s.startswith(p)), key=len)
        assert s in json.loads((SITE / pref[k]).read_text(encoding="utf-8"))["fiches"], s


def test_recherche_globale_sous_ensemble():
    g = json.loads((DOSSIER / "recherche_globale.json").read_text(encoding="utf-8"))
    assert len(g["entrees"]) <= entites.RECHERCHE_GLOBALE_MAX
    for s, nom, n in g["entrees"]:
        assert s in FICHES and FICHES[s]["denomination"] == nom and len(FICHES[s]["canaux"]) == n >= 2


def test_fonds_vert_jamais_relu_deux_fois():
    canaux = {c["id"]: c for c in INDEX["canaux"]}
    if not canaux["fonds_vert"]["lignes"]:
        pytest.skip("Fonds vert absent")
    for f in FICHES.values():
        for b in f["recoit"]:
            if b["canal"] == "subventions":
                assert all("subv_fonds_vert" not in x for x in b["fichiers"])


def test_mentions_sans_montant_et_probables_nationaux_sans_departement():
    for s, f in FICHES.items():
        for b in f["autres"]:
            if b["notion"] == "deliberations_publiees":
                assert all(v[1] is None for x in b["series"] for v in x["valeurs"]), s
        for p in f.get("probables", []):
            if p["canal"] == "presse_groupes":
                assert p["departement"] is None and len(entites.normaliser(p["nom_publie"]).split()) >= 2, s
            else:
                assert p["departement"], s
