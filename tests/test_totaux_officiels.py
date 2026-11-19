"""Grands totaux du site face aux chiffres officiels publiés (docs/VERIFICATION_TOTAUX.md), sans réseau.

La table versionnée docs/references_officielles.json donne, pour chaque grand total affiché : où le lire dans site/data,
la valeur officielle (document, tableau, millésime, URL), la tolérance justifiée et la classe du total :
  - conforme : |site - officiel| <= tolérance ;
  - ecart_explique : site - officiel = somme des composantes publiées (périmètre, méthode), à la tolérance près ;
  - erreur_corrigee : erreur trouvée et corrigée (avant / après), puis contrôlée comme les autres ;
  - non_verifiable : aucun chiffre officiel publié, motif écrit.
Une régénération de pipeline qui déplace un total hors de sa référence fait échouer ce test : il faut alors soit corriger
le pipeline, soit mettre à jour la référence (nouveau millésime officiel) en citant la source.

S'y ajoutent des contrôles internes que tests/test_coherence.py ne couvre pas : somme des enfants égale au nœud dans
toutes les racines d'arbres publiées (Sécurité sociale, administrations, millésimes), consolidation des administrations
publiques (transferts comptés une fois), total des opérateurs affiché égal au total de l'index.
"""
import glob
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
REF = json.loads((ROOT / "docs" / "references_officielles.json").read_text(encoding="utf-8"))
TOTAUX = REF["totaux"]
CLASSES = set(REF["classes"])
DOC = (ROOT / "docs" / "VERIFICATION_TOTAUX.md").read_text(encoding="utf-8")

_cache: dict = {}


def lire(rel: str):
    if rel not in _cache:
        chemin = SITE / rel
        if not chemin.exists():
            pytest.skip(f"absent : site/data/{rel}")
        _cache[rel] = json.loads(chemin.read_text(encoding="utf-8"))
    return _cache[rel]


def noeud(rel: str, id_: str):
    """Nœud d'un arbre par identifiant, en suivant les sous-fichiers (`fichier`) au besoin."""
    pile = [lire(rel)]
    while pile:
        n = pile.pop()
        if n.get("id") == id_:
            return n
        if n.get("fichier") and not n.get("enfants") and id_.startswith(n.get("id", "") + "/"):
            pile.append(lire(n["fichier"]))
        pile.extend(n.get("enfants", []))
    raise AssertionError(f"nœud {id_} absent de {rel}")


def valeur_site(spec: dict) -> float:
    rel = spec["fichier"]
    if "chemin" in spec:
        v = lire(rel)
        for k in spec["chemin"]:
            v = v[k]
        return float(v)
    if "noeud" in spec:
        return float(noeud(rel, spec["noeud"])["md"])
    calcul = spec["calcul"]
    if calcul == "racine_hors_psr":
        r = lire(rel)
        psr = next(e for e in r["enfants"] if e["nom"].startswith("Prelevements sur recettes"))
        return r["md"] - psr["md"]
    if calcul == "somme_ofgl":  # même calcul que web/src/ecrans/collectivites.ts (totalNational), en Md€
        b = lire(rel)
        i = b["agregats"].index(spec["agregat"])
        return sum(float((c["eur"].get(spec["annee"]) or [None] * (i + 1))[i] or 0) for c in b["collectivites"].values()) / 1e9
    if calcul == "annee_retours":
        return float(next(a for a in lire(rel)["annees"] if a["annee"] == spec["annee"])[spec["champ"]])
    if calcul == "somme_scsp_operateurs":  # même calcul que web/src/ecrans/operateurs.ts (totalScsp), en Md€
        return somme_scsp(spec["annee"]) / 1e9
    raise AssertionError(f"calcul inconnu : {calcul}")


def somme_scsp(annee: str) -> float:
    t = 0.0
    for o in lire("operateurs/operateurs.json")["operateurs"]:
        a = o["annees"].get(annee) or {}
        t += float(((a.get("financement_etat") or {}).get("scsp") or {}).get("cp_eur") or 0)
    return t


def composante(c: dict) -> float:
    v = c["valeur"] if "valeur" in c else valeur_site(c["site"])
    return c["signe"] * float(v)


IDS = [t["id"] for t in TOTAUX]


# ---------------------------------------------------------------------------------------------------------------------
# Table de référence : forme
# ---------------------------------------------------------------------------------------------------------------------


def test_table_reference_complete_et_documentee():
    assert len(IDS) == len(set(IDS)), "identifiants en double"
    for t in TOTAUX:
        assert t["classe"] in CLASSES, t["id"]
        assert t["libelle"] and t["ecran"] and t["unite"], t["id"]
        assert t["tolerance"]["justification"].strip(), t["id"]
        assert t["tolerance"]["absolue"] >= 0, t["id"]
        assert f"`{t['id']}`" in DOC, f"{t['id']} absent de docs/VERIFICATION_TOTAUX.md"
        o = t["officiel"]
        if t["classe"] == "non_verifiable" or "controle_interne" in t:
            assert o is None and t.get("motif", "").strip(), t["id"]
            continue
        for k in ("valeur", "document", "url", "millesime"):
            assert o.get(k) not in (None, ""), (t["id"], k)
        assert o["url"].startswith("https://"), t["id"]
        if t["classe"] == "ecart_explique":
            assert t["ecart"]["explication"].strip() and t["ecart"]["composantes"], t["id"]
            assert t.get("note_ecran", "").strip(), f"{t['id']} : écart de périmètre sans note à l'écran"
        if t["classe"] == "erreur_corrigee":
            assert t["correction"]["avant"].strip() and t["correction"]["apres"].strip(), t["id"]


def test_classes_resumees_dans_la_doc():
    for c in CLASSES:
        n = sum(t["classe"] == c for t in TOTAUX)
        assert f"| {c} | {n} |" in DOC, f"docs/VERIFICATION_TOTAUX.md : compte de la classe {c} ({n}) à mettre à jour"


# ---------------------------------------------------------------------------------------------------------------------
# Chaque total face au chiffre officiel
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("t", [t for t in TOTAUX if t["officiel"] is not None], ids=lambda t: t["id"])
def test_total_face_au_chiffre_officiel(t):
    site = valeur_site(t["site"])
    officiel = float(t["officiel"]["valeur"])
    tol = t["tolerance"]["absolue"]
    if "ecart" in t:
        attendu = sum(composante(c) for c in t["ecart"]["composantes"])
        assert math.isclose(site - officiel, attendu, abs_tol=tol), (
            f"{t['id']} : site {site} - officiel {officiel} = {site - officiel:.6f}, composantes {attendu:.6f}")
        assert abs(site - officiel) > tol, f"{t['id']} : plus d'écart, reclasser en conforme"
    else:
        assert abs(site - officiel) <= tol, f"{t['id']} : site {site}, officiel {officiel}, écart {site - officiel:.6f} > {tol}"


@pytest.mark.parametrize("t", [t for t in TOTAUX if t["classe"] == "erreur_corrigee"], ids=lambda t: t["id"])
def test_erreur_corrigee_ne_revient_pas(t):
    v = t["correction"].get("verification")
    if not v:
        return
    texte = lire(v["fichier"])[v["champ"]]
    assert v["absent"] not in texte and v["present"] in texte, t["id"]


@pytest.mark.parametrize("t", [t for t in TOTAUX if t["classe"] == "non_verifiable"], ids=lambda t: t["id"])
def test_total_non_verifiable_reste_calculable(t):
    assert valeur_site(t["site"]) > 0


def test_controles_internes_ont_leur_test():
    for t in TOTAUX:
        if "controle_interne" in t:
            assert (ROOT / t["controle_interne"]["test"]).exists(), t["id"]


# ---------------------------------------------------------------------------------------------------------------------
# Contrôles internes complémentaires (somme des parties, double compte)
# ---------------------------------------------------------------------------------------------------------------------

RACINES = sorted(p.relative_to(SITE).as_posix() for p in SITE.glob("**/racine.json"))


@pytest.mark.parametrize("rel", RACINES)
def test_somme_des_enfants_egale_le_noeud(rel):
    ecarts = []

    def w(n):
        enf = n.get("enfants")
        if n.get("fichier") and not enf and (SITE / n["fichier"]).exists():
            enf = lire(n["fichier"]).get("enfants")
        if enf and isinstance(n.get("md"), (int, float)) and all(isinstance(c.get("md"), (int, float)) for c in enf):
            s = sum(c["md"] for c in enf)
            if abs(s - n["md"]) > max(1e-3, 1e-6 * len(enf)):
                ecarts.append((n.get("id"), n["md"], round(s, 6)))
        for c in enf or []:
            w(c)

    w(lire(rel))
    assert not ecarts, ecarts[:10]


def test_administrations_consolidees_transferts_comptes_une_fois():
    """Ensemble (S13) consolidé : inférieur à la somme des sous-secteurs, l'écart étant les transferts entre eux."""
    for an, a in lire("administrations.json")["annees"].items():
        if not all(k in a and "TE" in a[k] for k in ("Ensemble", "Etat", "Collectivites locales", "Securite sociale")):
            continue
        somme = a["Etat"]["TE"] + a["Collectivites locales"]["TE"] + a["Securite sociale"]["TE"]
        assert a["Ensemble"]["TE"] < somme, an
        assert a["Ensemble"]["TR"] < a["Etat"]["TR"] + a["Collectivites locales"]["TR"] + a["Securite sociale"]["TR"], an
        # solde : les transferts s'annulent, l'ensemble égale la somme des soldes (arrondis au dixième)
        b9 = a["Etat"]["B9"] + a["Collectivites locales"]["B9"] + a["Securite sociale"]["B9"]
        assert abs(a["Ensemble"]["B9"] - b9) <= 0.25, (an, a["Ensemble"]["B9"], b9)


def test_operateurs_total_affiche_egal_index():
    idx = lire("operateurs/index.json")["totaux"]
    for an, t in idx.items():
        if "scsp_cp_eur" in t:
            assert abs(somme_scsp(an) - t["scsp_cp_eur"]) < 1, an


def test_psr_collectivites_et_ue_une_seule_fois_dans_l_arbre_etat():
    """Les transferts de l'État aux collectivités et à l'UE sont des prélèvements sur recettes : un seul nœud chacun."""
    for dossier in ("arbre", "arbre_lfi2025"):
        r = lire(f"{dossier}/racine.json")
        noms = []

        def w(n):
            noms.append(n["nom"])
            for c in n.get("enfants", []):
                w(c)

        w(r)
        assert sum(n.startswith("Prelevements sur recettes") for n in noms) == 1, dossier
        psr = next(e for e in r["enfants"] if e["nom"].startswith("Prelevements sur recettes"))
        assert {e["nom"] for e in psr["enfants"]} == {"Collectivités territoriales", "Union européenne"}, dossier
