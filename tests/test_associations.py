"""Tests des fichiers « associations » (site/data/associations), produits par `python pipeline/associations.py produire`.

Confidentialité : aucune adresse, aucun bénéficiaire nommé qui ne soit une personne morale vérifiée ; parlementaires
nommés seulement dans leur rôle public. Neutralité : ordre écrit dans chaque fichier et respecté. « nc » jamais 0.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import associations as A  # noqa: E402
import sirene  # noqa: E402
import vie_politique as vp  # noqa: E402

SITE = ROOT / "site" / "data"
AS = SITE / "associations"
TOL = 1.0


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _fichiers():
    return sorted(AS.rglob("*.json"))


def _norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _programmes() -> dict:
    """programme -> liste des parties (dans l'ordre)."""
    out = {}
    for f in sorted((AS / "programmes").glob("*.json")):
        d = _json(f)
        out.setdefault(d["programme"] or "sans_programme", []).append(d)
    for v in out.values():
        v.sort(key=lambda d: d["partie"])
    return out


INDEX = _json(AS / "index.json") if (AS / "index.json").exists() else None


def test_fichiers_presents():
    assert INDEX, "associations/index.json absent"
    assert (AS / "fonds_fondations.json").exists()
    noms = {f.name for f in (AS / "reserve").glob("*.json")}
    assert noms == {f"{a}_{y}.json" for a, y in A.RESERVES}
    for p in INDEX["programmes"]:
        for f in p["fichiers"]:
            assert (SITE / f).exists(), f


@pytest.mark.parametrize("f", _fichiers(), ids=lambda p: str(p.relative_to(AS)))
def test_millesime_source_et_taille(f):
    d = _json(f)
    assert d.get("millesime") and d.get("source"), f
    assert f.stat().st_size <= 5 * 1024 * 1024, f"{f} dépasse 5 Mo"


# --- Confidentialité ----------------------------------------------------------------------------------------------


CLES_INTERDITES = re.compile(r"adresse|code_postal|^ville$|prenom|naissance|courriel|email|telephone|dirigeant")


def _cles(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _cles(v)
    elif isinstance(x, list):
        for v in x:
            yield from _cles(v)


@pytest.mark.parametrize("f", _fichiers(), ids=lambda p: str(p.relative_to(AS)))
def test_aucune_cle_adresse_ni_donnee_personnelle(f):
    d = _json(f)
    fautes = {k for k in _cles(d) if CLES_INTERDITES.search(k)}
    for c in ("colonnes", "colonnes_beneficiaires"):
        fautes |= {k for k in d.get(c, []) if CLES_INTERDITES.search(k)}
    assert not fautes, fautes


def _nommes():
    """(fichier, siren, categorie_juridique) de chaque bénéficiaire nommé."""
    for parts in _programmes().values():
        for d in parts:
            for l in d["lignes"]:
                yield "programmes", l[0], l[2]
    for f in sorted((AS / "reserve").glob("*.json")):
        for p in _json(f)["parlementaires"]:
            for b in p["beneficiaires_nommes"]:
                yield f.name, b[0], b[2]


def test_beneficiaires_nommes_tous_personnes_morales():
    fautes = [(f, s, cj) for f, s, cj in _nommes() if not (sirene.siren_valide(s) and sirene.personne_morale(cj))]
    assert not fautes, fautes[:10]


def test_rnf_categorie_juridique_et_siret():
    d = _json(AS / "fonds_fondations.json")
    i_cj, i_siret = d["colonnes"].index("categorie_juridique"), d["colonnes"].index("siret")
    for l in d["lignes"]:
        assert l[i_cj] is None or sirene.personne_morale(l[i_cj]), l[:3]
        assert l[i_siret] is None or re.match(r"^\d{14}$", l[i_siret])


def test_textes_libres_sans_civilite():
    import local
    textes = []
    d = _json(AS / "fonds_fondations.json")
    i = d["colonnes"].index("objet_social")
    textes += [l[i] for l in d["lignes"] if l[i]]
    for f in sorted((AS / "reserve").glob("*.json")):
        textes += [b[6] for p in _json(f)["parlementaires"] for b in p["beneficiaires_nommes"] if b[6]]
    fautes = [t for t in textes if local.CIVILITE_RE.search(t)]
    assert not fautes, fautes[:5]


def _adresses_source() -> set[str]:
    """Adresses de la réserve (zone restreinte) : aucune ne doit se retrouver dans site/data."""
    import csv
    import io
    out = set()
    for d in sorted(A.RESTREINT.glob("assoc_reserve_*")):
        for p in sorted(d.glob("*.csv")):
            t = A._lire_texte(p)
            l1 = t.split("\n", 1)[0]
            rows = list(csv.reader(io.StringIO(t), delimiter=";" if l1.count(";") > l1.count(",") else ","))
            idx = [i for i, c in enumerate(rows[0]) if "adresse" in _norm(c)]
            for r in rows[1:]:
                for i in idx:
                    v = A.propre(r[i]) if i < len(r) else ""
                    if len(v) >= 18 and re.search(r"\d", v) and re.search(r"\b(rue|avenue|bd|boulevard|place|chemin|route)\b", v, re.I):
                        out.add(v)
    return out


@pytest.mark.skipif(not A.RESTREINT.exists(), reason="entrepôt restreint absent (runner sans data/lake)")
def test_aucune_adresse_de_la_reserve_publiee():
    adresses = _adresses_source()
    assert len(adresses) > 1000
    texte = "\n".join(f.read_text(encoding="utf-8") for f in (AS / "reserve").glob("*.json"))
    trouvees = [a for a in adresses if json.dumps(a, ensure_ascii=False)[1:-1] in texte]
    assert not trouvees, trouvees[:5]


def test_aucun_beneficiaire_non_apparie_nomme():
    """Un bénéficiaire nommé de la réserve porte toujours une méthode d'appariement et un SIREN vérifié."""
    for f in sorted((AS / "reserve").glob("*.json")):
        d = _json(f)
        for p in d["parlementaires"]:
            for b in p["beneficiaires_nommes"]:
                assert b[7] in ("commune_banatic", "jaune_meme_montant_programme", "api_nom_departement")
                assert b[0] and b[1], b


# --- Valeurs, conservation, « nc » --------------------------------------------------------------------------------


def test_nc_jamais_zero():
    for y in INDEX["annees"]:
        if y["statut"] == "nc":
            for k in ("total_source_eur", "nommes_eur", "associations_nommees"):
                assert y[k] == "nc", (y["annee"], k)
            assert y["raison"]
    annees_nc = {y["annee"] for y in INDEX["annees"] if y["statut"] == "nc"}
    assert annees_nc == set(A.INEXPLOITABLES)
    for parts in _programmes().values():
        for d in parts:
            idx_nc = [i for i, a in enumerate(d["annees"]) if a in annees_nc]
            for pa in d["par_annee"]:
                if pa["annee"] in annees_nc:
                    assert pa["statut"] == "nc" and pa["total_source_eur"] == "nc"
            for l in d["lignes"]:
                assert all(l[4][i] == "nc" for i in idx_nc), l[:2]
                assert len(l[4]) == len(d["annees"])


def test_conservation_par_programme_et_annee():
    for p, parts in _programmes().items():
        d0 = parts[0]
        for i, pa in enumerate(d0["par_annee"]):
            if pa["statut"] != "publie":
                assert pa["statut"] in ("nc", "absent_de_la_source")
                if pa["statut"] == "absent_de_la_source":
                    assert all(l[4][i] is None for d in parts for l in d["lignes"])
                continue
            s = pa["nommes_eur"] + pa["exclus_personnes_physiques_ou_non_identifies_eur"] + pa["non_verifies_eur"]
            assert abs(s - pa["total_source_eur"]) <= TOL, (p, pa["annee"])
            somme_lignes = sum(l[4][i] or 0 for d in parts for l in d["lignes"])
            assert abs(somme_lignes - pa["nommes_eur"]) <= TOL * max(1, len(d0["lignes"])) * 0.01 + TOL, (p, pa["annee"])
        for d in parts:
            for l in d["lignes"]:
                assert abs(sum(v for v in l[4] if isinstance(v, (int, float))) - l[3]) <= TOL, l[:2]


def test_totaux_index_egaux_aux_programmes():
    progs = _programmes()
    for i, y in enumerate(INDEX["annees"]):
        if y["statut"] != "publie":
            continue
        s = sum(parts[0]["par_annee"][i]["total_source_eur"] or 0 for parts in progs.values())
        assert abs(s - y["total_source_eur"]) <= TOL * len(progs), y["annee"]
        assert abs(y["nommes_eur"] + y["exclus_personnes_physiques_ou_non_identifies_eur"] + y["non_verifies_eur"]
                   - y["total_source_eur"]) <= TOL


def test_total_publie_plf2012_egal_somme_des_lignes():
    y = {x["annee"]: x for x in INDEX["annees"]}[2012]
    assert abs(y["total_publie_par_la_source_eur"] - y["total_source_eur"]) <= TOL


def test_correction_plf2013_documentee():
    y = {x["annee"]: x for x in INDEX["annees"]}[2013]
    c = y["correction"]
    assert c["facteur"] == 0.1 and c["part_montants_multiples_de_10"] >= 0.99
    assert all(abs(v["rapport_median"] - 10) < 0.05 for v in c["comparaison_annees_voisines"].values())


def test_conservation_reserve():
    for f in sorted((AS / "reserve").glob("*.json")):
        d = _json(f)
        assert abs(d["nommes_eur"] + d["agreges_eur"] - d["total_eur"]) <= TOL
        a = d["agreges"]
        assert abs(a["non_apparies_eur"] + a["dont_personnes_physiques_eur"] + a["non_verifies_eur"]
                   - d["agreges_eur"]) <= TOL
        assert abs(sum(p["total_eur"] for p in d["parlementaires"]) - d["total_eur"]) <= TOL * len(d["parlementaires"])
        for p in d["parlementaires"]:
            s = sum(b[5] for b in p["beneficiaires_nommes"]) + p["agreges"]["montant_eur"]
            assert abs(s - p["total_eur"]) <= TOL, p["parlementaire"]
        assert d["part_agregee_pct"] == round(d["agreges_eur"] / d["total_eur"] * 100, 2)


# --- Neutralité : ordre écrit et respecté ---------------------------------------------------------------------------


def test_ordre_ecrit_partout():
    for f in [AS / "fonds_fondations.json"] + sorted((AS / "reserve").glob("*.json")) + sorted((AS / "programmes").glob("*.json")):
        o = _json(f).get("ordre")
        assert o and len(o["regle"]) >= 20 and o["cles"], f


def test_ordre_reserve_neutre():
    for f in sorted((AS / "reserve").glob("*.json")):
        d = _json(f)
        ps = d["parlementaires"]
        cles = [(vp.cle_alpha(p["nom_tri"]), vp.cle_alpha(p["parlementaire"])) for p in ps]
        assert cles == sorted(cles), f.name
        for p in ps:
            b = p["beneficiaires_nommes"]
            k = [(-x[5], A.norm(x[1] or ""), x[0]) for x in b]
            assert k == sorted(k), p["parlementaire"]
        # aucun classement ni total par groupe politique
        assert "par_groupe" not in d and not any("groupe" in k for k in d if k != "regle_parlementaires")


def test_ordre_programmes_et_rnf():
    for parts in _programmes().values():
        lignes = [l for d in parts for l in d["lignes"]]
        k = [(-l[3], l[0]) for l in lignes]
        assert k == sorted(k)
    d = _json(AS / "fonds_fondations.json")
    k = [(vp.cle_alpha(A.norm(l[1] or "")), l[0]) for l in d["lignes"]]
    assert k == sorted(k)


# --- Unitaires (sans données) ---------------------------------------------------------------------------------------


def test_montants_et_programmes():
    assert A.montant("\xa0\xa0 3\xa0300,00") == 3300.0
    assert A.montant("71070.0") == 71070.0
    assert A.montant("") is None and A.montant(None) is None
    assert A.code_programme("P163 - Jeunesse") == "163"
    assert A.code_programme("206.0") == "206"
    assert A.code_programme("163-2") == "163"
    assert A.code_programme("Santé et sports: 219 - Sport") is None or A.code_programme("219 - Sport") == "219"
    assert A.siren_de(784810111) == "784810111" and A.siren_de("78481011") == "078481011"


def test_nom_commune_et_appariement():
    assert A.nom_commune("Commune de Saint-Jean-de-Luz") == "SAINT JEAN DE LUZ"
    assert A.nom_commune("MAIRIE D'AUMETZ") == "AUMETZ"
    assert A.nom_commune("ST PRIVAT LA MONTAGNE") == "SAINT PRIVAT LA MONTAGNE"
    communes = {("57", "AUMETZ"): "215700410"}
    ij = {(2016, "163", 1000): [("123456789", A.jetons("Comité des fêtes de Talange"), "57"),
                                ("987654321", A.jetons("Club de foot"), "57")]}
    l = {"beneficiaire": "Commune d'Aumetz", "dep": "57", "programme": "122", "montant": 5000.0}
    assert A.apparier_hors_ligne(l, 2016, communes, ij) == ("215700410", "commune_banatic")
    l = {"beneficiaire": "Comite des fetes Talange", "dep": "57", "programme": "163", "montant": 1000.0}
    assert A.apparier_hors_ligne(l, 2016, communes, ij) == ("123456789", "jaune_meme_montant_programme")
    l = {"beneficiaire": "Association sans rapport", "dep": "57", "programme": "163", "montant": 1000.0}
    assert A.apparier_hors_ligne(l, 2016, communes, ij) == (None, None)
    l = {"beneficiaire": "Comite des fetes Talange", "dep": "01", "programme": "163", "montant": 1000.0}
    assert A.apparier_hors_ligne(l, 2016, communes, ij) == (None, None)  # autre département


def test_personne_physique_jamais_nommee():
    import beneficiaires as B
    ext = {"123456789": {"cj": "1000", "trouve": True}, "222222222": {"cj": "2110", "trouve": True},
           "333333333": {"cj": "9220", "trouve": True, "nom": "ASSO"}}
    assert B.statut("123456789", None, ext)[0] == "pp"
    assert B.statut("222222222", None, ext)[0] != "pm"
    assert B.statut("333333333", None, ext)[0] == "pm"
    assert B.statut("NR CHORUS", None, ext)[0] == "ni"
