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
