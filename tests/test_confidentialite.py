# tests/test_confidentialite.py
"""Aucune donnee de personne physique hors elus et candidats dans site/data."""
import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site" / "data"
CJ_INTERDITES = re.compile(r"^(1\d{3}|2110|2210|2310|2385)$")
CLES_INTERDITES = {"donateur", "donateurs", "mandataire", "mandataire_financier", "adresse",
                   "date_naissance", "naissance", "courriel", "email", "telephone", "iban"}


def _parcourir(x, colonnes=None):
    if isinstance(x, dict):
        yield from ((k, v) for k, v in x.items())
        for v in x.values():
            yield from _parcourir(v, x.get("colonnes"))
    elif isinstance(x, list):
        if colonnes and "categorie_juridique" in colonnes and len(x) == len(colonnes) \
                and not any(isinstance(v, (list, dict)) for v in x):
            yield "categorie_juridique", x[colonnes.index("categorie_juridique")]
        for v in x:
            yield from _parcourir(v, colonnes)


def test_aucune_personne_physique_publiee():
    fautes = []
    for f in SITE.rglob("*.json"):
        for cle, val in _parcourir(json.loads(f.read_text(encoding="utf-8"))):
            if cle in CLES_INTERDITES or (cle == "categorie_juridique" and CJ_INTERDITES.match(str(val or ""))):
                fautes.append(f"{f.relative_to(SITE)} : {cle}={str(val)[:40]}")
    assert not fautes, "\n".join(fautes[:20])


def test_rien_de_restreint_dans_site():
    assert not [p for p in SITE.rglob("*") if "_restreint" in p.parts]


def test_groupements_de_personnes_physiques_jamais_nommes():
    import sys
    sys.path.insert(0, str(SITE.parents[1] / "pipeline"))
    import sirene
    for cj in ("1000", "2110", "2210", "2310", "2385", "", None, "0"):
        assert not sirene.personne_morale(cj), cj
    for cj in ("5710", "9220", "7210", "2900"):
        assert sirene.personne_morale(cj), cj


# --- Audit avant lancement (18/11/2026) : coordonnées, domiciliations, adresses de biens privés -------------------
COURRIEL = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
TELEPHONE = re.compile(r"(?<![\d/])(?:\+33\s?|\(?0)[1-9](?:[\s.-]?\d{2}){4}(?![\d/])")
CLES_NOMS = {"denomination", "nom", "nom_usuel", "beneficiaire", "titulaire"}


def _chaines(x, cle=None):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _chaines(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v, cle)
    elif isinstance(x, str):
        yield cle, x


def test_aucun_courriel_ni_telephone_dans_les_noms_publies():
    fautes = []
    for f in SITE.rglob("*.json"):
        for cle, s in _chaines(json.loads(f.read_text(encoding="utf-8"))):
            if "@" in s and COURRIEL.search(s) and not s.startswith(("http", "mailto:")):
                fautes.append(f"{f.relative_to(SITE)} [{cle}] courriel : {s[:60]}")
            elif cle in CLES_NOMS and TELEPHONE.search(s):
                fautes.append(f"{f.relative_to(SITE)} [{cle}] téléphone : {s[:60]}")
    assert not fautes, "\n".join(fautes[:20])


def test_filtres_domiciliation_telephone_adresse():
    import sys
    sys.path.insert(0, str(SITE.parents[1] / "pipeline"))
    import associations, local, ue
    assert associations.sans_domiciliation("ASSOCIATION X CHEZ M. JEAN DUPONT") == "ASSOCIATION X"
    assert associations.sans_domiciliation("CLUB Y CHEZ MME MARTIN - 28") == "CLUB Y - 28"
    assert associations.sans_domiciliation("CHEZ MOI") == "CHEZ MOI"
    assert ue.sans_telephone("SOCIETE Z (04 67605982)") == "SOCIETE Z"
    assert ue.sans_telephone("FRANCE 2030 SAS") == "FRANCE 2030 SAS"
    assert local.objet_avec_adresse("Restauration du patrimoine immobilier privé - dossier 1 rue Neuve")
    assert not local.objet_avec_adresse("Subvention au comité des fêtes")


def test_aucune_domiciliation_chez_une_personne_ni_adresse_dans_les_subventions_deliberees():
    import sys
    sys.path.insert(0, str(SITE.parents[1] / "pipeline"))
    import associations, local
    fautes = []
    for f in (SITE / "associations").rglob("*.json"):
        for cle, s in _chaines(json.loads(f.read_text(encoding="utf-8"))):
            if associations.sans_domiciliation(s) != s:
                fautes.append(f"{f.relative_to(SITE)} : {s}")
    for f in (SITE / "local" / "decisions").glob("*/index.json"):
        for a, lst in (json.loads(f.read_text(encoding="utf-8")).get("deliberations_subventions") or {}).items():
            fautes += [f"{f.relative_to(SITE)} {a} : {d[2]}" for d in lst if local.objet_avec_adresse(d[2])]
    assert not fautes, "\n".join(fautes[:20])


def test_representants_d_interets_sans_siren_jamais_nommes_par_un_nom_de_personne():
    import sys
    sys.path.insert(0, str(SITE.parents[1] / "pipeline"))
    import controle
    assert controle.nom_de_personne_seul("JEAN DUPONT")
    assert not controle.nom_de_personne_seul("FONDATION JEAN DUPONT")
    d = json.loads((SITE / "controle" / "lobbying" / "organisations.json").read_text(encoding="utf-8"))
    fautes = [o[2] for o in d["organisations"] if o[1] != "SIREN" and controle.nom_de_personne_seul(o[2])]
    assert not fautes and {"BEATRICE NERE", "GILLES SAVARY CONSULTANTS"}.isdisjoint(o[2] for o in d["organisations"])
