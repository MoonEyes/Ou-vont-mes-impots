"""Fonds de solidarité (pipeline/fonds_solidarite.py) : fonctions pures et cohérence des fichiers publiés, sans réseau."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "fonds_solidarite"
sys.path.insert(0, str(ROOT / "pipeline"))
import fonds_solidarite as fs  # noqa: E402


def _json(nom: str):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


def test_nombre_absent_jamais_zero():
    assert fs.nombre("") is None and fs.nombre(None) is None and fs.nombre("nc") is None
    assert fs.nombre("0") == 0 and fs.nombre("2791110.00") == 2791110 and fs.nombre("12,6") == 13


def test_lecture_csv_avec_bom():
    lignes = fs.lire_csv("﻿a,b\n1,2\n".encode("utf-8"))
    assert lignes == [{"a": "1", "b": "2"}]


def test_instantanes_ordonnes_un_par_mois():
    assert fs.INSTANTANES == sorted(fs.INSTANTANES)
    mois = [d[:7] for d in fs.INSTANTANES]
    assert len(mois) == len(set(mois))
    assert fs.INSTANTANES[-1] == fs.DERNIER_VOLET1


def test_aucune_entreprise_nommee_et_agregats_coherents():
    d = _json("departements.json")
    for cle in ("par_section", "par_categorie_juridique", "par_classe_effectif"):
        t = d[cle]
        assert len(t["colonnes"]) == 5
        for l in t["lignes"]:
            assert len(l) == 5 and all(v is None or isinstance(v, int) for v in l[2:])
    texte = json.dumps(d, ensure_ascii=False)
    for interdit in ("siren", "siret", "denomination", "nom_"):
        assert interdit not in texte


def test_cumuls_de_fin_de_mois_non_additionnes():
    i = _json("index.json")
    m = _json("regions_mois.json")
    dates = {l[0] for l in m["lignes"]}
    assert dates <= set(i["instantanes"]["fins_de_mois"])
    assert {l[1] for l in m["lignes"]} == {1, 2}
    # chaque ligne est publiée telle quelle : pas de ligne « total » ni de montant mensuel calculé
    assert all(l[2] != "total" and l[3] != "total" for l in m["lignes"])
    assert any("ne calcule pas de différence" in x["pourquoi"] for x in i["manques"])
