"""Tests unitaires de pipeline/sirene.py : filtre de confidentialité (personne morale), validation SIREN et
résolution via l'API simulée (aucun appel réseau : requests.get est remplacé)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import sirene  # noqa: E402


@pytest.mark.parametrize("s,ok", [
    ("123456789", True), (123456789, True), ("12345678", False), ("1234567890", False),
    ("12345678A", False), ("", False), (None, False), (" 123456789", False),
])
def test_siren_valide(s, ok):
    assert sirene.siren_valide(s) is ok


@pytest.mark.parametrize("cj,ok", [
    ("5710", True), ("7210", True), ("9220", True), ("4110", True), (5710, True),
    ("1000", False),  # entrepreneur individuel
    ("2110", False), ("2210", False), ("2310", False), ("2385", False),  # groupements de personnes physiques
    ("2900", True),  # autre groupement de droit privé (personne morale)
    ("0000", False), ("", False), (None, False), ("571", False), ("57100", False), ("ABCD", False),
])
def test_personne_morale(cj, ok):
    assert sirene.personne_morale(cj) is ok


def test_personne_morale_flottant_reste_prudent():
    # une catégorie lue en flottant (« 5710.0 ») n'est pas reconnue : refus, donc jamais publiée par erreur
    assert sirene.personne_morale(5710.0) is False


class _Rep:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data or {}

    def json(self):
        return self._data


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(sirene, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(sirene.time, "sleep", lambda s: None)
    reponses = {}
    monkeypatch.setattr(sirene.requests, "get", lambda url, params, **kw: reponses[params["q"]])
    return reponses


def test_interroger_ne_garde_jamais_le_nom_d_une_personne_physique(api):
    api["111111111"] = _Rep(200, {"results": [{"siren": "111111111", "nature_juridique": "1000",
                                               "nom_complet": "JEAN DUPONT"}]})
    api["222222222"] = _Rep(200, {"results": [{"siren": "222222222", "nature_juridique": "5710",
                                               "nom_complet": " ACME SAS "}]})
    api["333333333"] = _Rep(200, {"results": [{"siren": "999999999", "nature_juridique": "5710"}]})
    api["444444444"] = _Rep(404)
    api["555555555"] = _Rep(200, {"results": [{"siren": "555555555", "nature_juridique": "2110",
                                               "nom_complet": "INDIVISION MARTIN"}]})
    assert sirene._interroger("111111111") == {"cj": "1000", "trouve": True}
    assert sirene._interroger("222222222") == {"cj": "5710", "trouve": True, "nom": "ACME SAS"}
    assert sirene._interroger("333333333") == {"cj": None, "trouve": False}
    assert sirene._interroger("444444444") == {"cj": None, "trouve": False}
    assert "nom" not in sirene._interroger("555555555")


def test_interroger_api_saturee_renvoie_none(api):
    api["666666666"] = _Rep(429)
    assert sirene._interroger("666666666") is None


def test_resoudre_complete_et_sauve_le_cache(api):
    api["222222222"] = _Rep(200, {"results": [{"siren": "222222222", "nature_juridique": "5710",
                                               "nom_complet": "ACME"}]})
    api["777777777"] = _Rep(503)
    cache = {"888888888": {"cj": "7210", "trouve": True}}
    res, restants = sirene.resoudre(["222222222", "222222222", "invalide", "888888888", "777777777"],
                                    cache=cache, paralleles=2)
    assert res["222222222"]["nom"] == "ACME"
    assert "777777777" not in res and restants == 1
    assert json.loads(sirene.CACHE.read_text(encoding="utf-8")) == res
    assert sirene.charger_cache() == res


def test_charger_cache_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(sirene, "CACHE", tmp_path / "absent.json")
    assert sirene.charger_cache() == {}


def test_sauver_fusionne_avec_le_disque(monkeypatch, tmp_path):
    # une autre collecte a ecrit entre-temps : ses entrees ne sont pas perdues, une categorie connue n'est pas
    # ecrasee par une entree sans categorie, et le cache en memoire est complete
    monkeypatch.setattr(sirene, "CACHE", tmp_path / "cache.json")
    sirene.CACHE.write_text(json.dumps({"111111111": {"cj": "5710", "trouve": True, "nom": "A"},
                                        "222222222": {"cj": "7210", "trouve": True}}), encoding="utf-8")
    mien = {"222222222": {"cj": None, "trouve": False}, "333333333": {"cj": "9220", "trouve": True}}
    sirene._sauver(mien)
    disque = json.loads(sirene.CACHE.read_text(encoding="utf-8"))
    assert set(disque) == {"111111111", "222222222", "333333333"}
    assert disque["222222222"]["cj"] == "7210"
    assert mien == disque
    assert not list(tmp_path.glob("*.part"))


def _ecrire_cache(args):
    chemin, debut, n = args
    sys.path.insert(0, str(ROOT / "pipeline"))
    import sirene as s
    s.CACHE = Path(chemin)
    for i in range(debut, debut + n):
        s._sauver({f"{i:09d}": {"cj": "5710", "trouve": True}})


def test_sauver_concurrent_ne_perd_aucune_entree(tmp_path):
    # quatre processus ecrivent chacun 25 SIREN distincts, une sauvegarde par SIREN : l'union complete est sur disque
    import multiprocessing
    chemin = str(tmp_path / "cache.json")
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        pool.map(_ecrire_cache, [(chemin, k * 100, 25) for k in range(4)])
    disque = json.loads(Path(chemin).read_text(encoding="utf-8"))
    assert set(disque) == {f"{k * 100 + i:09d}" for k in range(4) for i in range(25)}
    assert not list(tmp_path.glob("*.part"))
