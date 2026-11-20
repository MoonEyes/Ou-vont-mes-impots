"""Salaires de la fonction publique (pipeline/salaires_fonction_publique.py) : fonctions pures et fichiers publiés."""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "salaires_fonction_publique"
sys.path.insert(0, str(ROOT / "pipeline"))
import salaires_fonction_publique as sfp  # noqa: E402


def _json(nom: str):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


def test_valeur_absente_jamais_zero():
    assert sfp.valeur("") is None and sfp.valeur("nc") is None and sfp.valeur("s") is None
    assert sfp.valeur("2548") == 2548.0 and sfp.valeur("-1,34") == -1.34


def test_lecture_zip_melodi(tmp_path):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("X_data.csv", '"SEX";"TIME_PERIOD";"OBS_VALUE"\n"F";2023;2000\n')
        f.writestr("X_metadata.csv", '"COD_VAR";"LIB_VAR";"COD_MOD";"LIB_MOD"\n"SEX";"Sexe";"F";"Femme"\n')
    lignes, lib, var = sfp.lire_zip(z)
    assert lignes == [{"SEX": "F", "TIME_PERIOD": "2023", "OBS_VALUE": "2000"}]
    assert lib == {"SEX": {"F": "Femme"}} and var == {"SEX": "Sexe"}


def test_fichiers_publies_tels_que_l_insee():
    idx = _json("index.json")
    for cle in ("series_longues", "annuel"):
        d = _json(f"{cle}.json")
        meta = idx["jeux"][cle]
        assert len(d["observations"]) == meta["observations"]
        dims = d["colonnes"][1:-1]
        for i, dim in enumerate(dims):
            codes = {o[i + 1] for o in d["observations"]}
            assert codes == set(meta["nomenclatures"][dim]["modalites"]), (cle, dim)
        assert d["observations"] == sorted(d["observations"], key=lambda x: tuple(str(c) for c in x[:-1]))
    sl = _json("series_longues.json")
    assert min(o[0] for o in sl["observations"]) <= 1996 and max(o[0] for o in sl["observations"]) >= 2023


def test_aucun_calcul_par_personne():
    idx = _json("index.json")
    assert any("aucun calcul par personne" in r for r in idx["regles"])
    assert set(idx["jeux"]["series_longues"]["nomenclatures"]["DERA_MEASURE"]["modalites"]) <= {
        "SALAIRE_NET_EQTP_MENSUEL_MOYEN_EUROS_CONSTANTS", "SALAIRE_NET_EQTP_MENSUEL_MOYEN_EVOLUTION_CONSTANT",
        "SALAIRE_NET_EQTP_MENSUEL_MOYEN_INDICE_100_1996"}
