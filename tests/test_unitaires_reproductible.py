"""Tests unitaires de pipeline/reproductible.py (date de la collecte la plus récente, manifeste construit à la main)
et du décodage des pièces jointes de pipeline/fetch.py."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import fetch  # noqa: E402
import reproductible as r  # noqa: E402


def test_date_sources_par_domaine(monkeypatch, tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({
        "a": {"domaine": "etat", "collecte_le": "2026-03-01T10:00:00Z"},
        "b": {"domaine": "etat", "collecte_le": "2026-05-02T23:30:00+02:00"},
        "c": {"domaine": "local", "collecte_le": "2026-06-10T08:00:00"},  # sans fuseau : UTC
        "d": {"domaine": "local"},
        "e": "entrée invalide",
    }), encoding="utf-8")
    monkeypatch.setattr(r, "MANIFESTE", m)
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    assert r.date_sources("etat") == "2026-05-02"
    assert r.date_sources("etat", avec_heure=True) == "2026-05-02T21:30:00Z"
    assert r.date_sources() == "2026-06-10"
    assert r.date_sources("local", avec_heure=True) == "2026-06-10T08:00:00Z"


def test_date_sources_epoch_prioritaire(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "MANIFESTE", tmp_path / "absent.json")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert r.date_sources(avec_heure=True) == "1970-01-01T00:00:00Z"


def test_decode_csv_utf8_bom_et_utf16():
    assert fetch.decode_csv("﻿a;é".encode("utf-8")) == "a;é"
    assert fetch.decode_csv("a;é".encode("utf-8")) == "a;é"
    assert fetch.decode_csv("a;é".encode("utf-16")) == "a;é"


def test_write_json_trie_les_cles(tmp_path):
    p = tmp_path / "x" / "y.json"
    fetch.write_json(p, {"b": 1, "a": "é"})
    assert p.read_text(encoding="utf-8") == '{\n "a": "é",\n "b": 1\n}\n'
