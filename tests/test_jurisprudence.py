"""Jurisprudence administrative (pipeline/jurisprudence.py) : lecture de l'en-tête sans texte ni nom, comptes publiés."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOSSIER = ROOT / "site" / "data" / "jurisprudence"
sys.path.insert(0, str(ROOT / "pipeline"))
import jurisprudence as jur  # noqa: E402

XML = """<?xml version="1.0" encoding="UTF-8"?><TEXTE_JURI_ADMIN><META><META_COMMUN><ID>CETATEXT000055005460</ID>
<ORIGINE>CETAT</ORIGINE></META_COMMUN><META_SPEC><META_JURI><TITRE>Conseil d'État, 16/10/2026, 504654</TITRE>
<DATE_DEC>2026-10-16</DATE_DEC><JURIDICTION>Conseil d'État</JURIDICTION><NUMERO>504654</NUMERO></META_JURI>
<META_JURI_ADMIN><FORMATION>8ème chambre</FORMATION><TYPE_REC>Plein contentieux fiscal</TYPE_REC>
<PUBLI_RECUEIL>B</PUBLI_RECUEIL><PRESIDENT>M. Jean Dupont</PRESIDENT><AVOCATS>SCP MARTIN</AVOCATS></META_JURI_ADMIN>
</META_SPEC></META><TEXTE><BLOC_TEXTUEL><CONTENU>M. A... Durand demande...</CONTENU></BLOC_TEXTUEL>
<SOMMAIRE><ANA><SCT ID="8A" TYPE="PRINCIPAL">19-04-02-01 CONTRIBUTIONS ET TAXES. - IMPÔTS SUR LES REVENUS ET BÉNÉFICES. - Résumé qui cite M. Durand.</SCT></ANA></SOMMAIRE></TEXTE></TEXTE_JURI_ADMIN>""".encode()


def test_en_tete_lu_sans_texte_ni_nom():
    ligne, plan = jur.lire_xml(XML)
    assert ligne["id"] == "CETATEXT000055005460" and ligne["numero"] == "504654" and ligne["codes"] == "19-04-02-01"
    tout = json.dumps([ligne, plan], ensure_ascii=False)
    for nom in ("Dupont", "MARTIN", "Durand", "Résumé"):
        assert nom not in tout
    assert ("19", "CONTRIBUTIONS ET TAXES") in plan and ("19-04", "IMPÔTS SUR LES REVENUS ET BÉNÉFICES") in plan


def test_juridictions_normalisees_et_matieres():
    assert jur.juridiction("Conseil d'Etat") == jur.juridiction("Conseil d'État") == "Conseil d'État"
    assert jur.juridiction("CAA de PARIS") == jur.juridiction("COUR ADMINISTRATIVE D'APPEL DE PARIS") \
        == "Cour administrative d'appel de Paris"
    assert jur.juridiction("CAA de VERSAILLESS") == "Cour administrative d'appel de Versailles"
    assert jur.juridiction("Tribunal administratif d'Amiens") == "Tribunal administratif d'Amiens"
    m = jur.matieres("19-04|54-01", "Plein contentieux fiscal")
    assert m["fiscale_classement"] and m["fiscale_type_recours"] and not m["budgetaire_classement"]
    assert jur.matieres("", "Excès de pouvoir")["classee"] is False


def _json(nom):
    p = DOSSIER / nom
    if not p.exists():
        pytest.skip(f"{p} absent")
    return json.loads(p.read_text(encoding="utf-8"))


def test_comptes_et_liens_coherents():
    idx = _json("index.json")
    c = _json("comptes.json")
    for l in c["lignes"]:
        an, j, n, classees, fisc, fisc_tr, budg = l
        assert j in idx["juridictions"] and classees <= n and fisc <= classees and budg <= classees and fisc_tr <= n
    for an, f in idx["fichiers"]["decisions"].items():
        d = json.loads((DOSSIER.parent / f["chemin"]).read_text(encoding="utf-8"))
        assert len(d["decisions"]) == f["decisions"]
        attendu = sum(l[4] for l in c["lignes"] if l[0] == int(an)) + sum(l[6] for l in c["lignes"] if l[0] == int(an))
        assert f["decisions"] <= attendu
        assert all(x[0].startswith(("CETATEXT", "JURITEXT")) or "TEXT" in x[0] for x in d["decisions"])
    for f in DOSSIER.rglob("*.json"):
        t = f.read_text(encoding="utf-8")
        assert "M. " not in t and "Mme " not in t, f   # aucune civilité, donc aucun nom de personne
