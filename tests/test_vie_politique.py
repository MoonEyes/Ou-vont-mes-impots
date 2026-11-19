"""Tests sans reseau des fichiers « vie politique » (site/data/vie_politique), produits par
`python pipeline/vie_politique.py produire`."""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import vie_politique  # noqa: E402

SITE = ROOT / "site" / "data"
VP = SITE / "vie_politique"
CANDIDATS = VP / "candidats"
# Decision du 19/11/2026 : les parlementaires candidats nationaux y sont nommes (amendements, votes nominatifs).
PARLEMENTAIRES_NOMMES = {SITE / "decisions", SITE / "qui_a_vote"}
TOL = 1.0  # euro


def _json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _fichiers(dossier: Path = VP):
    return sorted(dossier.rglob("*.json"))


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _chaines(obj, exclure_cles=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in exclure_cles:
                yield from _chaines(v, exclure_cles)
    elif isinstance(obj, list):
        for v in obj:
            yield from _chaines(v, exclure_cles)
    elif isinstance(obj, str):
        yield obj


def _ngrammes(texte: str, n_max: int = 5):
    t = _norm(texte).split()
    for n in range(2, n_max + 1):
        for i in range(len(t) - n + 1):
            yield " ".join(t[i:i + n])


def _noms_candidats(seulement=None) -> set[str]:
    """Noms des candidats lus dans le detail (publie si AFFICHER_CANDIDATS, sinon restreint et non versionne)."""
    dossier = CANDIDATS if vie_politique.AFFICHER_CANDIDATS else vie_politique.RESTREINT
    noms = set()
    for f in sorted(dossier.glob("*.json")):
        if seulement and not any(f.stem.startswith(s) for s in seulement):
            continue
        for c in _json(f)["candidats"]:
            for morceau in re.split(r"\bet\b", c["candidat"]):
                n = _norm(morceau)
                if len(n.split()) >= 2 and len(n) >= 8:
                    noms.add(n)
    return noms


def test_fichiers_presents():
    assert (VP / "annees.json").exists()
    assert list((VP / "scrutins").glob("presidentielle_*.json")), "presidentielles absentes"
    assert list((VP / "partis").glob("*.json"))


@pytest.mark.parametrize("f", _fichiers(), ids=lambda p: str(p.relative_to(VP)))
def test_millesime_source_et_taille(f):
    d = _json(f)
    assert d.get("millesime") and d.get("source"), f
    assert f.stat().st_size <= 5 * 1024 * 1024, f"{f} depasse 5 Mo"


@pytest.mark.parametrize("f", sorted((VP / "partis").glob("*.json")), ids=lambda p: p.name)
def test_conservation_partis(f):
    d = _json(f)
    p = d["partis"]
    assert abs(sum(x["total_eur"] for x in p) - d["total_eur"]) <= TOL * len(p)
    assert abs(sum(x["premiere_fraction_eur"] for x in p) - d["total_premiere_fraction_eur"]) <= TOL * len(p)
    assert abs(sum(x["seconde_fraction_eur"] for x in p) - d["total_seconde_fraction_eur"]) <= TOL * len(p)
    for x in p:
        assert abs(x["premiere_fraction_eur"] + x["seconde_fraction_eur"] - x["total_eur"]) <= TOL
    assert d["nombre_partis_beneficiaires"] == len(p)


@pytest.mark.parametrize("f", sorted((VP / "scrutins").glob("*.json")), ids=lambda p: p.name)
def test_conservation_scrutins(f):
    d = _json(f)
    assert d["nombre_candidats"] == sum(v["nombre"] for v in d["decisions"].values())
    if d.get("par_nuance"):
        for champ in ("depenses_totales_eur", "remboursement_etat_total_eur", "apport_personnel_total_eur"):
            s = sum(n[champ] or 0 for n in d["par_nuance"])
            assert abs(s - (d[champ] or 0)) <= TOL * len(d["par_nuance"]), champ
        assert sum(n["nombre_candidats"] for n in d["par_nuance"]) == d["nombre_candidats"]
    # Le detail par candidat (publie ou restreint) redonne les memes totaux.
    dossier = CANDIDATS if vie_politique.AFFICHER_CANDIDATS else vie_politique.RESTREINT
    detail = dossier / f.name
    if detail.exists():
        c = _json(detail)["candidats"]
        assert len(c) == d["nombre_candidats"]
        s = sum(x.get("remboursement_eur") or 0 for x in c)
        assert abs(s - (d["remboursement_etat_total_eur"] or 0)) <= TOL * len(c)


def test_annees_conservation_et_part():
    a = _json(VP / "annees.json")
    for y in a["annees"]:
        p = y["programme_232"]
        if p:
            assert abs(sum(p["actions_eur"].values()) - p["total_actions_01_a_03_eur"]) <= TOL
            if p.get("euros_sur_100_euros_etat") is not None:
                assert abs(100 * p["total_actions_01_a_03_eur"] / p["denominateur_eur"] - p["euros_sur_100_euros_etat"]) < 1e-3
        s = sum(r["remboursement_etat_total_eur"] or 0 for r in y["remboursements_campagne"])
        assert abs(s - y["remboursements_campagne_total_eur"]) <= TOL
        if y["aide_publique_partis"]:
            pa = _json(VP / y["aide_publique_partis"]["fichier"])
            assert abs(pa["total_eur"] - y["aide_publique_partis"]["total_eur"]) <= TOL
    # 2018 a 2025 : exécution du programme 232 presente (trou 2021 comble par le rapport parlementaire).
    presentes = {y["annee"] for y in a["annees"] if y["programme_232"]}
    assert set(range(2018, 2026)) <= presentes


def test_remboursements_inferieurs_a_l_organisation_des_elections():
    """Coherence : remboursements arretes pour les scrutins de l'annee <= action « Organisation des elections ».
    Quand l'une des deux valeurs manque, le controle doit etre explicitement signale (coherent = None + note)."""
    a = _json(VP / "annees.json")
    for c in a["controle_remboursements_vs_organisation_des_elections"]:
        if c["organisation_des_elections_eur"] is None:
            assert c["coherent"] is None and c.get("note"), c
        else:
            assert c["remboursements_eur"] <= c["organisation_des_elections_eur"], c
            assert c["coherent"] is True


def test_presidentielles_reference_page_et_bornes():
    for annee in (2012, 2017, 2022):
        d = _json(VP / "scrutins" / f"presidentielle_{annee}.json")
        assert d["nombre_candidats"] >= 9
        assert d["remboursement_etat_total_eur"] > 30e6
    dossier = CANDIDATS if vie_politique.AFFICHER_CANDIDATS else vie_politique.RESTREINT
    for f in sorted(dossier.glob("presidentielle_*.json")):
        for c in _json(f)["candidats"]:
            assert re.search(r"décision p\. \d+, article 2 p\. \d+", c["reference"]), c
            assert c["remboursement_eur"] <= c["depenses_eur"] + TOL, c
            assert c["remboursement_eur"] <= 0.475 * 22_509_000 + TOL  # 47,5 % du plafond du second tour


# --- Regle personnes physiques -------------------------------------------------------------------------------------

def test_candidats_publies_seulement_si_drapeau_et_liste_blanche():
    publies = sorted(CANDIDATS.glob("*.json")) if CANDIDATS.exists() else []
    if not vie_politique.AFFICHER_CANDIDATS:
        assert not publies, "AFFICHER_CANDIDATS est faux : aucun detail par candidat ne doit etre publie"
        return
    assert publies
    autorises = set(vie_politique.CHAMPS_PUBLIES)
    interdits = re.compile(r"adresse|naissance|donateur|mandataire|civilit|sexe|profession|email|telephone", re.I)
    for f in publies:
        d = _json(f)
        for c in d["candidats"]:
            assert set(c) <= autorises, (f.name, set(c) - autorises)
        assert not interdits.search(" ".join(d.get("champs", []))), f.name
        for c in d["candidats"][:50]:
            assert not re.match(r"^(M|Mme|Mlle)\.?\s", c["candidat"]), "civilite non retiree"


def test_aucun_nom_de_candidat_hors_du_dossier_candidats():
    """Aucun nom de candidat dans site/data/vie_politique hors de candidats/ (les noms de partis, personnes
    morales publiees par la CNCCFP, sont exclus du controle), ni, pour les candidats nationaux (presidentielles,
    tetes de liste europeennes), ailleurs dans site/data. Exception (decision du proprietaire du 19/11/2026) : un
    parlementaire qui a ete candidat national est nomme comme les autres dans decisions/ et qui_a_vote/ (auteur
    d'amendement, vote nominatif, objet du scrutin tel que publie)."""
    noms = _noms_candidats()
    if not noms:
        pytest.skip("detail par candidat absent (lancer pipeline/vie_politique.py produire)")
    fuites = []
    for f in _fichiers():
        if CANDIDATS in f.parents:
            continue
        d = _json(f)
        exclure = ("nom",) if f.parent.name == "partis" else ()
        for s in _chaines(d, exclure):
            for g in _ngrammes(s):
                if g in noms:
                    fuites.append((f.name, g))
    assert not fuites, fuites[:20]
    nationaux = _noms_candidats(seulement=("presidentielle_", "europeennes_"))
    for f in SITE.rglob("*.json"):
        if CANDIDATS in f.parents or VP / "partis" in f.parents or PARLEMENTAIRES_NOMMES & set(f.parents):
            continue
        texte = f.read_text(encoding="utf-8")
        if not re.search(r"[A-Z]{3,}", texte):
            continue
        for s in _chaines(json.loads(texte)):
            for g in _ngrammes(s, 4):
                assert g not in nationaux, (f.relative_to(SITE), g)


def test_restreint_non_versionne():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/processed/_restreint/" in gi
