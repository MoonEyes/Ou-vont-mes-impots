"""Lexique neutre des libellés de site/data (charte docs/NEUTRALITE.md, règle 2).

Même liste que le test du site (web/tests/ecrans.test.ts) : docs/lexique_neutre.json. On contrôle les textes écrits
par le pipeline (avertissements, limites, lectures, définitions, règles, méthodes, périmètres, notes, tendances,
règles d'ordre). Les données reproduites telles quelles (titres de rapports, objets de subventions, noms de communes,
de candidats ou d'organisations, intitulés d'indicateurs) ne sont pas de la rédaction du site et ne sont pas contrôlées.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
LEXIQUE = json.loads((ROOT / "docs" / "lexique_neutre.json").read_text(encoding="utf-8"))

# Clés dont la valeur est rédigée par le pipeline (et tout ce qu'elles contiennent).
CLES_REDACTION = {
    "avertissement", "avertissements", "limites", "lecture", "lecture_ecart", "note", "notes", "note_perimetre",
    "composantes_note", "definition", "definitions", "regle", "regle_personnes", "methode", "perimetre", "constat",
    "trous", "explication", "justification", "raison", "variante", "annee_donnees_note", "effet", "motif",
    "reculs_criteres", "hypothese", "hypotheses", "non_sourcé", "parts", "ordre",
}


def _borne(corps: str) -> re.Pattern:
    # \w de Python est Unicode : les lettres accentuées comptent comme lettres.
    return re.compile(rf"(?<!\w)(?:{corps})(?!\w)", re.I)


REGLES = [(_borne("|".join(r["termes"])), r["raison"]) for r in LEXIQUE["regles"]]
NICHE = _borne("niches?")
NICHE_DEFINIE = re.compile(LEXIQUE["niche_definie"], re.I)


def textes(x, cle: str | None = None, dans: bool = False):
    """(clé, texte) pour chaque chaîne rédigée par le pipeline ; la valeur d'une tendance est toujours contrôlée."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from textes(v, k, dans or k in CLES_REDACTION)
        t = x.get("tendance")
        if isinstance(t, dict) and isinstance(t.get("valeur"), str):
            yield "tendance.valeur", t["valeur"]
        if isinstance(x.get("tendances"), dict):  # comptes par valeur de tendance (realisations/index.json)
            yield from (("tendances", k) for k in x["tendances"])
    elif isinstance(x, list):
        for v in x:
            yield from textes(v, cle, dans)
    elif isinstance(x, str) and dans:
        yield cle, x


def fautes(texte: str) -> list[str]:
    t = texte
    for e in LEXIQUE["exceptions"]:
        t = t.replace(e, " ")
    out = [raison for r, raison in REGLES if r.search(t)]
    if NICHE.search(NICHE_DEFINIE.sub(" ", t)):
        out.append("« niche » sans sa définition (dépense fiscale ou exonération de cotisations)")
    return out


def test_lexique_charge_et_regles_actives():
    assert len(REGLES) >= 10
    for exemple in ("seulement 3 %", "un écart énorme", "elle coûte", "pèse sur", "en recul", "la niche sociale",
                    "le lobbying", "un cadeau fiscal"):
        assert fautes(exemple), exemple
    for neutre in ("dans le sens souhaité publié", "coût complet moyen", "plus de 120 sources",
                   "exonérations de cotisations (souvent appelées niches sociales)",
                   "Entreprises et « niches » fiscales et sociales"):
        assert not fautes(neutre), neutre


FICHIERS = sorted(DATA.rglob("*.json"))


@pytest.mark.parametrize("dossier", sorted({f.relative_to(DATA).parts[0] for f in FICHIERS}))
def test_libelles_des_donnees_neutres(dossier):
    erreurs = []
    for f in (x for x in FICHIERS if x.relative_to(DATA).parts[0] == dossier):
        for cle, t in textes(json.loads(f.read_text(encoding="utf-8"))):
            for raison in fautes(t):
                erreurs.append(f"{f.relative_to(DATA)} [{cle}] {raison} : {t[:120]}")
    assert not erreurs, "\n".join(erreurs[:20])


def test_tendances_relatives_au_sens_publie():
    idx = json.loads((DATA / "realisations" / "index.json").read_text(encoding="utf-8"))
    assert set(idx["tendances"]) <= {"dans le sens souhaité publié", "à l’inverse du sens souhaité publié", "stable",
                                     "sens inconnu"}


def test_ordre_explicite_partis_et_candidats():
    for f in sorted((DATA / "vie_politique" / "partis").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["ordre"]["cles"] == ["-total_eur", "nom_tri"], f.name
        cles = [(-p["total_eur"], p["nom_tri"]) for p in d["partis"]]
        assert [c[0] for c in cles] == sorted(c[0] for c in cles), f.name
        assert all(p["nom_tri"] and p["nom"] for p in d["partis"]), f.name
    for f in sorted((DATA / "vie_politique" / "candidats").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["ordre"]["cles"] == ["circonscription", "candidat"], f.name


def test_aides_entreprises_titres_reels_et_annees():
    d = json.loads((DATA / "controle" / "aides_entreprises.json").read_text(encoding="utf-8"))
    for e in d["estimations"]:
        assert not re.match(r"idem\b", e["publication"], re.I), e["id"]
        assert e["annee_donnees"] is not None or e.get("annee_donnees_note"), e["id"]
