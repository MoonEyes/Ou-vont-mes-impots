"""« Ma commune » (pipeline/ma_commune.py) : normalisation des noms, correspondance code postal -> commune, cas
particuliers (code partagé, communes nouvelles, arrondissements de Paris, Lyon et Marseille, hors périmètre) sur un
petit extrait fabriqué ; puis contrôles des fichiers publiés dans site/data/ma_commune (sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import ma_commune as mc  # noqa: E402

SORTIE = ROOT / "site" / "data" / "ma_commune"

EXTRAIT = """#Code_commune_INSEE;Nom_de_la_commune;Code_postal;Libellé_d_acheminement;Ligne_5
44066;GRANDCHAMP DES FONTAINES;44119;GRANDCHAMP DES FONTAINES;
44209;TREILLIERES;44119;TREILLIERES;
49021;BEAUFORT EN ANJOU;49250;BEAUFORT EN ANJOU;BEAUFORT EN VALLEE
49021;BEAUFORT EN ANJOU;49250;BEAUFORT EN ANJOU;GEE
49021;BEAUFORT EN ANJOU;49250;BEAUFORT EN ANJOU;
75111;PARIS 11;75011;PARIS;
75116;PARIS 16;75016;PARIS;
75116;PARIS 16;75116;PARIS;
69381;LYON 01;69001;LYON;
13213;MARSEILLE 13;13013;MARSEILLE;
97502;ST PIERRE;97500;ST PIERRE ET MIQUELON;ST PIERRE
99138;MONACO;98000;MONACO;
"""

GEO = {
    "44066": {"nom": "Grandchamp-des-Fontaines", "dep": "44", "population": 7062},
    "44209": {"nom": "Treillières", "dep": "44", "population": 10600},
    "49021": {"nom": "Beaufort-en-Anjou", "dep": "49", "population": 6901},
    "75056": {"nom": "Paris", "dep": "75", "population": 2103778},
    "69123": {"nom": "Lyon", "dep": "69", "population": 520774},
    "13055": {"nom": "Marseille", "dep": "13", "population": 886040},
}


@pytest.fixture()
def produit(tmp_path, monkeypatch):
    csv = tmp_path / "cp.csv"
    csv.write_bytes(EXTRAIT.encode("latin-1"))
    monkeypatch.setattr(mc, "lire_geo", lambda: GEO)
    monkeypatch.setattr(mc, "fichier_cp", lambda: csv)
    monkeypatch.setattr(mc, "version_source", lambda: "2026-11-17")
    monkeypatch.setattr(mc, "date_sources", lambda *a, **k: "2026-11-19")
    sortie = tmp_path / "sortie"
    index = mc.produire(sortie)
    return sortie, index


def lire(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_normalisation():
    assert mc.norm("Saint-Étienne-du-Rouvray") == "saint etienne du rouvray"
    assert mc.norm("ST ETIENNE DU ROUVRAY") == "saint etienne du rouvray"
    assert mc.norm("Ste-Foy-lès-Lyon") == "sainte foy les lyon"
    assert mc.norm("L'Haÿ-les-Roses") == "l hay les roses"
    assert mc.norm("Œuilly") == "oeuilly"
    assert mc.joli("ST GEORGES DES GARDES") == "Saint Georges des Gardes"
    assert mc.compacte("l abergement") == "labergement"


def test_arrondissements_ramenes_a_la_commune():
    assert mc.vers_commune("75111") == ("75056", "11e arrondissement")
    assert mc.vers_commune("75101") == ("75056", "1er arrondissement")
    assert mc.vers_commune("69389") == ("69123", "9e arrondissement")
    assert mc.vers_commune("13216") == ("13055", "16e arrondissement")
    assert mc.vers_commune("13004") == ("13004", None)
    assert mc.vers_commune("69380") == ("69380", None)


def test_code_partage_localites_et_hors_perimetre(produit):
    sortie, index = produit
    cp44 = lire(sortie / "cp" / "44.json")
    assert [e[0] for e in cp44["codes_postaux"]["44119"]] == ["44066", "44209"]
    assert cp44["millesime"] and cp44["source"] and cp44["date_sources"] == "2026-11-19"
    cp49 = lire(sortie / "cp" / "49.json")
    assert cp49["codes_postaux"]["49250"] == [["49021", "Beaufort-en-Anjou", "49", 6901, "Beaufort en Vallee, Gee"]]
    cp75 = lire(sortie / "cp" / "75.json")["codes_postaux"]
    assert cp75["75011"] == [["75056", "Paris", "75", 2103778, "11e arrondissement"]]
    assert cp75["75116"][0][4] == "16e arrondissement"
    assert "97" not in index["prefixes_cp"] and "98" not in index["prefixes_cp"]
    assert index["hors_perimetre"]["codes_postaux"] == 2
    assert set(index["hors_perimetre"]["territoires"]) == {"Saint-Pierre-et-Miquelon", "Monaco"}
    c = index["couverture"]
    assert c["communes_avec_code_postal"] == 6 and c["communes_sans_code_postal"] == []
    assert c["codes_postaux_partages"] == 1 and c["communes_max_par_code_postal"] == 2
    assert c["communes_plusieurs_codes_postaux"] == 1          # Paris : 75011, 75016, 75116
    assert c["localites"] == 2 and c["arrondissements"] == 4


def test_noms_communes_localites_arrondissements(produit):
    sortie, index = produit
    tous = [e for cle in index["cles_noms"] for e in lire(sortie / "noms" / f"{cle}.json")["noms"]]
    par_nom = {e[1]: e for e in tous}
    assert par_nom["Beaufort en Vallee"] == ["49021", "Beaufort en Vallee", "49", 6901, "49250", "localite"]
    assert par_nom["Paris"][4] == "75011 75016 75116" and par_nom["Paris"][5] == "commune"
    assert par_nom["Paris 16e arrondissement"][4] == "75016 75116"
    assert par_nom["Paris 16e arrondissement"][5] == "arrondissement"
    assert {e[0] for e in tous if e[5] == "commune"} == set(GEO)
    # fichier de noms = préfixe de la clé compacte
    for cle in index["cles_noms"]:
        for e in lire(sortie / "noms" / f"{cle}.json")["noms"]:
            assert mc.compacte(mc.norm(e[1])).startswith(cle)


def test_code_insee_inconnu_arrete_la_production(tmp_path, monkeypatch):
    csv = tmp_path / "cp.csv"
    csv.write_bytes((EXTRAIT + "01999;INCONNUE;01000;INCONNUE;\n").encode("latin-1"))
    monkeypatch.setattr(mc, "lire_geo", lambda: GEO)
    monkeypatch.setattr(mc, "fichier_cp", lambda: csv)
    monkeypatch.setattr(mc, "version_source", lambda: None)
    monkeypatch.setattr(mc, "date_sources", lambda *a, **k: "2026-11-19")
    with pytest.raises(SystemExit, match="01999"):
        mc.produire(tmp_path / "s")


def test_decoupage_des_noms():
    entrees = [[f"saint {chr(97 + i % 26)}{i}", "x", "y", "44", 1, "", "commune"] for i in range(6000)]
    entrees += [["sai", "x", "Sai", "61", 1, "", "commune"]]
    groupes = mc.decouper(entrees)
    assert all(len(v) <= mc.SEUIL_DECOUPE for v in groupes.values())
    assert sum(len(v) for v in groupes.values()) == len(entrees)
    assert "sai" in groupes and groupes["sai"][0][2] == "Sai"


# --- fichiers publiés ---------------------------------------------------------------------------------------------

publie = pytest.mark.skipif(not (SORTIE / "index.json").exists(), reason="site/data/ma_commune non produit")


@publie
def test_publie_couvre_toutes_les_communes_du_code_geographique():
    index = lire(SORTIE / "index.json")
    geo = {}
    for f in (ROOT / "site" / "data" / "local" / "geo").glob("*.json"):
        geo.update(lire(f)["communes"])
    c = index["couverture"]
    assert c["communes_cog"] == len(geo)
    assert c["communes_avec_code_postal"] + len(c["communes_sans_code_postal"]) == len(geo)
    communes = set()
    for cle in index["cles_noms"]:
        for e in lire(SORTIE / "noms" / f"{cle}.json")["noms"]:
            assert e[0] in geo
            if e[5] == "commune":
                communes.add(e[0])
                assert e[1] == geo[e[0]]["nom"]
    assert communes == set(geo)
    vus = set()
    for p in index["prefixes_cp"]:
        d = lire(SORTIE / "cp" / f"{p}.json")
        for cp, entrees in d["codes_postaux"].items():
            assert cp.startswith(p)
            for e in entrees:
                assert e[0] in geo and e[2] == geo[e[0]]["departement"]
                vus.add(e[0])
    assert len(vus) == c["communes_avec_code_postal"]
    for cle in ("75056", "69123", "13055"):
        assert cle in vus and cle in index["arrondissements"]


@publie
def test_publie_tailles_et_entetes():
    fichiers = sorted(SORTIE.rglob("*.json"))
    index = lire(SORTIE / "index.json")
    assert len(fichiers) == 1 + len(index["prefixes_cp"]) + len(index["cles_noms"])
    for f in fichiers:
        assert f.stat().st_size < mc.MAX_OCTETS, f
        d = lire(f)
        assert d["millesime"] and "La Poste" in d["source"], f
    assert {r["verdict"] for r in index["recherche_publique"]} <= {"réutilisable tel quel", "à adapter",
                                                                    "inspiration seulement"}


@publie
def test_aucune_donnee_de_personne():
    """La base ne contient que des communes et des localités : aucun champ de personne, d'adresse ou de contact."""
    texte = "".join(f.read_text(encoding="utf-8") for f in SORTIE.rglob("*.json")).lower()
    for mot in ("courriel", "telephone", "téléphone", "dirigeant", "adresse_", "prenom", "prénom"):
        assert mot not in texte, mot


@pytest.mark.skipif(not mc.F_CP.exists(), reason="entrepôt absent : reproductibilité non vérifiable ici")
def test_deux_productions_identiques(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    mc.produire(a)
    mc.produire(b)
    fa = sorted(p.relative_to(a) for p in a.rglob("*.json"))
    assert fa == sorted(p.relative_to(b) for p in b.rglob("*.json"))
    for p in fa:
        assert (a / p).read_bytes() == (b / p).read_bytes(), p
