"""Cohérence croisée des données publiées (site/data) et du contrat d'interface, sans réseau ni data/lake.

Chaque test applique une règle de docs/QUALITE.md (identifiant R..). Un écart publié et documenté est une tolérance
explicite (constante TOL_* ou liste d'exceptions nommée), jamais un échec. Un vrai défaut relevé par la relecture est
marqué xfail(strict=True) avec la référence de son constat (B = bloquant, I = important, M = mineur) : la correction du
défaut fait échouer le xfail, ce qui oblige à retirer la marque.
"""
import glob
import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"

if not (SITE / "arbre" / "racine.json").exists():
    pytest.skip("site/data/arbre absent", allow_module_level=True)

_cache: dict = {}


def lire(rel: str):
    if rel not in _cache:
        _cache[rel] = json.loads((SITE / rel).read_text(encoding="utf-8"))
    return _cache[rel]


def existe(rel: str) -> bool:
    return (SITE / rel).exists()


def besoin(*rels):
    manquants = [r for r in rels if not existe(r)]
    if manquants:
        pytest.skip(f"absent : {', '.join(manquants)}")


RACINE = lire("arbre/racine.json")
TOTAL_MD = RACINE["md"]


def _programmes(dossier="arbre"):
    """{numéro: (nœud, grand poste, mission)} des nœuds `programme` de la racine d'une vue."""
    out = {}

    def w(n, gp=None, mi=None):
        if n["niveau"] == "grand_poste":
            gp = n["nom"]
        if n["niveau"] == "mission":
            mi = n["nom"]
        if n["niveau"] == "programme":
            out[n["id"].split("/")[-1]] = (n, gp, mi)
            return
        for c in n.get("enfants", []):
            w(c, gp, mi)

    w(lire(f"{dossier}/racine.json"))
    return out


PROG = _programmes()


def _noeud(racine, id_):
    pile = [racine]
    while pile:
        n = pile.pop()
        if n["id"] == id_:
            return n
        pile.extend(n.get("enfants", []))
    return None


def _grand_poste(nom_prefixe):
    return next(c for c in RACINE["enfants"] if c["nom"].startswith(nom_prefixe))


PSR = _grand_poste("Prelevements sur recettes")
PSR_UE = next(m for m in PSR["enfants"] if m["nom"] == "Union européenne")
PSR_COLL = next(m for m in PSR["enfants"] if m["nom"].startswith("Collectivit"))


def _nature():
    out = {}
    for f in glob.glob(str(SITE / "nature" / "*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        out[d["programme"]] = d
    return out


# ---------------------------------------------------------------------------------------------------------------------
# R01-R03 Arbre État et sankey
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dossier", ["arbre", "arbre_lfi2025", "arbre_plf2025_nature"])
def test_R01_arbre_noeud_egale_somme_enfants(dossier):
    besoin(f"{dossier}/racine.json")
    ecarts = []

    def w(n):
        enf = n.get("enfants")
        if n.get("fichier"):
            sous = lire(n["fichier"])
            enf = sous.get("enfants")
            if abs(sous["md"] - n["md"]) > 1e-6:
                ecarts.append((n["id"], "fichier", n["md"], sous["md"]))
        if enf:
            s = sum(c["md"] for c in enf)
            # arrondi à 6 décimales de chaque enfant
            if abs(s - n["md"]) > 1e-6 * (len(enf) + 1):
                ecarts.append((n["id"], n["md"], s))
            for c in enf:
                w(c)

    w(lire(f"{dossier}/racine.json"))
    assert not ecarts, ecarts[:10]


def test_R02_racine_programmes_plus_psr_et_meta():
    s = sum(n["md"] for n, _, _ in PROG.values()) + PSR["md"]
    assert abs(s - TOTAL_MD) < 1e-4
    m = lire("meta.json")["controle"]["etat"]["execution_2024"]
    assert abs(m["total_md"] - TOTAL_MD) < 1e-4
    assert abs(m["total_hors_psr_md"] - (TOTAL_MD - PSR["md"])) < 1e-3
    for mission in PSR["enfants"]:
        assert abs(m["prelevements_sur_recettes_md"][mission["nom"]] - mission["md"]) < 1e-3
    # compléments PLRG (programmes absents du budget vert) = nœuds de l'arbre
    for p, v in m["complements_plrg_md"].items():
        assert abs(PROG[p][0]["md"] - v) < 1e-3, p


@pytest.mark.parametrize("fichier,dossier", [("sankey_etat.json", "arbre"), ("sankey_etat_lfi2025.json", "arbre_lfi2025")])
def test_R03_sankey_conservation_et_psr(fichier, dossier):
    besoin(fichier)
    s = lire(fichier)
    racine = lire(f"{dossier}/racine.json")
    par_niveau = defaultdict(float)
    for l in s["links"]:
        par_niveau[s["nodes"][l["source"]]["level"]] += l["value"]
        assert l["value"] > 0
    for niv, v in par_niveau.items():
        assert abs(v - s["total"]) < 1e-3, (niv, v, s["total"])  # arrondi à 4 décimales par lien
    neg = sum(p["md"] for p in s["programmes_negatifs_hors_sankey"])
    assert abs(s["total"] + neg - s["total_net_arbre"]) < 1e-3
    assert abs(s["total_net_arbre"] - racine["md"]) < 1e-3
    psr = next(c for c in racine["enfants"] if c["nom"].startswith("Prelevements"))
    ids = {n["id"]: i for i, n in enumerate(s["nodes"])}
    for m in psr["enfants"]:
        i = ids[f"psr:{m['nom']}"]
        v = sum(l["value"] for l in s["links"] if l["target"] == i)
        assert abs(v - m["md"]) < 1e-3, m["nom"]


# ---------------------------------------------------------------------------------------------------------------------
# R04-R10 Union européenne
# ---------------------------------------------------------------------------------------------------------------------


def test_R04_psr_ue_egale_arbre_serie_tracabilite_retours():
    besoin("ue/contribution.json", "ue/retours.json")
    c = lire("ue/contribution.json")
    p = c["psr_ue"]
    assert p["noeud_arbre"] == PSR_UE["id"]
    assert abs(p["md"] - PSR_UE["md"]) < 1e-6
    assert abs(p["eur_sur_100_budget_etat"] - PSR_UE["md"] / TOTAL_MD * 100) < 0.005
    serie = {s["annee"]: s for s in c["serie_psr_ue"]}
    assert abs(serie[p["annee"]]["execute_md"] - p["md"]) < 1e-3
    r = {a["annee"]: a for a in lire("ue/retours.json")["annees"]}
    assert abs(r[p["annee"]]["psr_ue_execute_md"] - p["md"]) < 1e-3
    if existe("tracabilite/noeud_psr_union_europeenne.json"):
        t = lire("tracabilite/noeud_psr_union_europeenne.json")
        assert t["id_arbre"] == PSR_UE["id"]
        assert abs(t["total_eur"] - PSR_UE["md"] * 1e9) < 1000


def test_R05_psr_lfi2025_egale_serie_vote_et_meta():
    besoin("arbre_lfi2025/racine.json", "ue/contribution.json")
    r = lire("arbre_lfi2025/racine.json")
    psr = next(c for c in r["enfants"] if c["nom"].startswith("Prelevements"))
    ue = next(m for m in psr["enfants"] if m["nom"] == "Union européenne")
    serie = {s["annee"]: s for s in lire("ue/contribution.json")["serie_psr_ue"]}
    assert abs(serie[2025]["vote_md"] - ue["md"]) < 1e-3
    m = lire("meta.json")["controle"]["etat"]["lfi_2025"]
    for mi in psr["enfants"]:
        assert abs(m["prelevements_sur_recettes_md"][mi["nom"]] - mi["md"]) < 1e-3


def test_R06_deficit_psr_egale_arbre():
    d = lire("deficit.json")["etat"]["annees"]
    assert abs(d["Exécution 2024"]["prelevements_sur_recettes_md"] - PSR["md"]) < 1e-3
    if existe("arbre_lfi2025/racine.json") and "LFI 2025" in d:
        r = lire("arbre_lfi2025/racine.json")
        psr = next(c for c in r["enfants"] if c["nom"].startswith("Prelevements"))
        assert abs(d["LFI 2025"]["prelevements_sur_recettes_md"] - psr["md"]) < 1e-3


def test_R07_retours_contribution_deduite_et_psr_serie():
    besoin("ue/retours.json", "ue/contribution.json")
    serie = {s["annee"]: s for s in lire("ue/contribution.json")["serie_psr_ue"]}
    for a in lire("ue/retours.json")["annees"]:
        assert abs(a["contribution_comptable_md"] - (a["retours_md"] - a["solde_net_comptable_md"])) < 1e-3, a["annee"]
        if a["annee"] in serie:
            assert abs(a["psr_ue_execute_md"] - serie[a["annee"]]["execute_md"]) < 1e-3, a["annee"]


# Tolérance publiée (constat M9) : 24,3 Md€ (Sénat, arrondi au dixième) contre 24,356 Md€ déduit (retours - solde).
TOL_CONTRIBUTION_COMPTABLE_MD = 0.1


def test_R08_contribution_comptable_2024_deux_sources():
    besoin("ue/retours.json", "ue/contribution.json")
    c = lire("ue/contribution.json")["contribution_comptable_2024_md"]
    r = next(a for a in lire("ue/retours.json")["annees"] if a["annee"] == 2024)
    assert abs(c - r["contribution_comptable_md"]) <= TOL_CONTRIBUTION_COMPTABLE_MD


def test_R09_usage_rubriques_somme_100():
    besoin("ue/contribution.json")
    c = lire("ue/contribution.json")
    rub = c["usage"]["rubriques"]
    assert abs(sum(r["part"] for r in rub) - 1) < 1e-5
    assert abs(sum(r["contribution_france_md"] for r in rub) - c["psr_ue"]["md"]) < 1e-4
    assert abs(sum(r["eur_sur_100"] for r in rub) - 100) < 0.05
    for r in rub:
        assert abs(sum(p["part"] for p in r["poles"]) - r["part"]) < 1e-5, r["code"]
        assert abs(sum(p["contribution_france_md"] for p in r["poles"]) - r["contribution_france_md"]) < 1e-4
        assert abs(r["contribution_france_md"] - r["part"] * c["psr_ue"]["md"]) < 1e-3
    u = c["usage"]
    assert abs(u["cfp_total_md"] - u["poles_total_md"] - u["marges_exclues_md"]) < 1e-3


def test_R10_engagements_fts_somme():
    besoin("ue/contribution.json")
    pe = lire("ue/contribution.json")["programmes_engagements"]
    assert abs(sum(p["md"] for p in pe["programmes"]) + pe["autres"]["md"] - pe["total_md"]) < 1e-3
    assert abs(sum(p["part"] for p in pe["programmes"]) + pe["autres"]["md"] / pe["total_md"] - 1) < 1e-4


# ---------------------------------------------------------------------------------------------------------------------
# R11-R13 Dette
# ---------------------------------------------------------------------------------------------------------------------


def test_R11_programme_117_arbre_dette_realisations_meta():
    besoin("dette/interets.json")
    p117 = PROG["117"][0]["md"]
    b = lire("dette/interets.json")["budgetaire"]["annees"]["2024"]
    assert b["md"] is not None and abs(b["md"] - p117) < 1e-3
    if existe("realisations/117.json"):
        r = next(a for a in lire("realisations/117.json")["prevu_depense"]["annees"] if a["annee"] == 2024)
        assert abs(r["depense_constatee_eur"] / 1e9 - p117) < 1e-6
    assert abs(lire("meta.json")["controle"]["etat"]["execution_2024"]["complements_plrg_md"]["117"] - p117) < 1e-3
    if existe("decisions/programme_117.json"):
        assert abs(lire("decisions/programme_117.json")["annees"]["2024"]["depenses_cp"] / 1e9 - p117) < 1e-6
    lect = lire("dette/interets.json")["cas_type"]["lecture_budgetaire_etat"]
    assert abs(lect["part_programme_117_dans_arbre_etat"] - p117 / TOTAL_MD) < 5e-4


def test_R12_tracabilite_dette_anonyme_par_nature():
    besoin("tracabilite/programme_117.json", "tracabilite/programme_369.json", "tracabilite/resume.json")
    for p in ("117", "369"):
        t = lire(f"tracabilite/programme_{p}.json")
        assert abs(t["parts"]["anonyme_par_nature"]["eur"] - t["total_eur"]) < 1, p
    g = lire("tracabilite/resume.json")["global"]["parts"]["anonyme_par_nature"]["eur"]
    assert g >= (PROG["117"][0]["md"] + PROG["369"][0]["md"]) * 1e9 - 1000


def test_R13_dette_cas_type_coherence_interne():
    besoin("dette/interets.json", "dette/index.json", "administrations.json")
    d = lire("dette/interets.json")
    ct = d["cas_type"]
    pa = ct["par_administration"]
    assert abs(sum(v["montant_annuel_eur"] for v in pa.values()) - ct["total_annuel_eur"]) < 0.02
    # somme de parts arrondies au centime : 0,01 € d'écart toléré avec la borne centrale
    assert abs(ct["total_annuel_eur"] - ct["fourchette_eur"]["central"]) <= 0.02
    assert abs(sum(v["sur_100_eur"] for v in pa.values()) - 100) <= 0.02
    sect = d["nationale"]["eurostat"]["secteurs"]
    for nom, v in pa.items():
        assert abs(v["interets_annuel_eur"] - v["montant_annuel_eur"] * v["part_interets_dans_depenses"]) < 0.02, nom
        assert abs(v["part_interets_dans_depenses"] - sect[v["secteur"]]["part_depenses"][ct["annee_ratios"]]) < 1e-9
    assert abs(sum(v["interets_annuel_eur"] for v in pa.values()) - ct["interets_annuel_eur"]) < 0.02
    assert abs(ct["interets_annuel_eur"] / ct["total_annuel_eur"] * 100 - ct["interets_sur_100_eur"]) < 0.006
    assert lire("dette/index.json")["synthese"]["interets_sur_100_eur_cas_c04"] == ct["interets_sur_100_eur"]
    # ratio = D41 / TE de administrations.json (même Eurostat)
    adm = lire("administrations.json")["annees"][ct["annee_ratios"]]
    corres = {"S13": "Ensemble", "S1311": "Etat", "S1313": "Collectivites locales", "S1314": "Securite sociale"}
    for s, a in corres.items():
        x = sect[s]
        assert abs(x["md"][ct["annee_ratios"]] / adm[a]["TE"] - x["part_depenses"][ct["annee_ratios"]]) < 1e-4, s


# ---------------------------------------------------------------------------------------------------------------------
# R14-R15 Cas type 2 100 € net (C04) : pipeline, cas types, web
# ---------------------------------------------------------------------------------------------------------------------

CAS_TYPES = json.loads((ROOT / "tests" / "cas_types" / "cas_types.json").read_text(encoding="utf-8"))
C04 = next(c for c in CAS_TYPES["cas"] if c["id"] == "C04")


def _c04_hors_bulletin():
    """Décile du cas C04 et montants centraux recalculés depuis site/data."""
    ref = C04["reference_openfisca"]
    pers = ref["personnes"]["declarant1"]
    salaire = pers["cotisations_salariales"] + pers["csg"] + pers["crds"] + ref["foyer"]["impot_revenu"]
    revenu_dispo = pers["salaire_net_avant_impot"] - ref["foyer"]["impot_revenu"]
    tva = lire("prelevements/tva_conso.json")
    bornes = tva["deciles_niveau_de_vie"]["bornes_eur_par_an"]
    decile = 1 + sum(1 for b in bornes if revenu_dispo >= b)  # 1 UC (célibataire)
    tr = next(t for t in tva["tranches"] if t["decile"] == decile)
    return salaire, tr


def test_R14_cas_type_c04_pipeline_egale_reference_et_donnees():
    besoin("dette/interets.json", "prelevements/tva_conso.json", "prelevements/taxe_fonciere/69.json")
    ct = lire("dette/interets.json")["cas_type"]
    assert ct["profil"]["cas_type"] == "C04"
    assert C04["profil"]["personnes"][0]["salaire_net_avant_impot_mensuel"] == 2100
    assert ct["commune"].startswith(C04["profil"]["residence"]["commune_insee"])
    salaire, tr = _c04_hors_bulletin()
    conso = tr["taxes_produits_eur_par_uc"]
    teom = lire("prelevements/taxe_fonciere/69.json")["communes"]["69123"][3:6]
    v = ct["variantes"]["lyon"]
    assert abs(v["teom_eur"] - teom[1]) < 0.01
    # salaire et IR : moteur du site contre OpenFisca, 1 € de tolérance (cas types, tolérance 1 %)
    assert abs(ct["fourchette_eur"]["central"] - (salaire + conso["central"] + teom[1])) <= 1.0
    assert abs(ct["fourchette_eur"]["haut"] - (salaire + conso["haut"] + teom[2])) <= 1.0
    assert abs(ct["fourchette_eur"]["bas"] - (salaire + conso["bas"] + teom[0])) <= 1.0
    # « Plusieurs » = autres taxes sur les produits, sans affectation sourcée (hors-bulletin.ts)
    assert abs(ct["par_administration"]["Plusieurs"]["montant_annuel_eur"] - tr["detail_eur_par_uc"]["autres"]["central"]) < 0.01
    # la variante sans commune ne diffère que par la TEOM
    sc = ct["variantes"]["sans_commune"]
    assert abs(v["fourchette_eur"]["central"] - sc["fourchette_eur"]["central"] - v["teom_eur"]) < 0.02


def test_R14b_libelle_commune_du_cas_type():
    """Constat M1 (corrigé) : seule la variante principale est la commune du cas type C04 ; une autre variante ne
    s'en réclame jamais."""
    besoin("dette/interets.json")
    ct = lire("dette/interets.json")["cas_type"]
    commune_c04 = C04["profil"]["residence"]["commune_insee"]
    assert ct["commune"].startswith(commune_c04)
    for nom, x in ct["variantes"].items():
        if not x["commune"] or x["commune"] == ct["commune"]:
            continue
        assert not x["commune"].startswith(commune_c04), nom
        assert "commune du cas type" not in x["commune"], (nom, x["commune"])
        if "cas type" in x["commune"]:  # la mention du cas type renvoie à sa vraie commune
            assert commune_c04 in x["commune"], (nom, x["commune"])


def test_R14c_affichage_web_egale_pipeline():
    """web/affichage_lyon.json (écrit par web/tests/ecrans.test.ts, non versionné) = fourchette publiée."""
    f = ROOT / "web" / "affichage_lyon.json"
    if not f.exists():
        pytest.skip("web/affichage_lyon.json absent : lancer `npm test` dans web/")
    besoin("dette/interets.json")
    web = json.loads(f.read_text(encoding="utf-8"))
    pub = lire("dette/interets.json")["cas_type"]["fourchette_eur"]
    for k in ("bas", "central", "haut"):
        assert abs(web[k] - pub[k]) < 0.005, k


FIXT = ROOT / "web" / "tests" / "fixtures" / "data"


def _fixture(rel):
    p = FIXT / rel
    if not p.exists():
        pytest.skip(f"fixture absente : {rel}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_R15_fixtures_web_entrees_du_cas_type_egales_site():
    """Les entrées du calcul personnel dans les fixtures web sont celles publiées (sinon le test web ne prouve rien)."""
    a = _fixture("prelevements/affectation.json")
    b = lire("prelevements/affectation.json")
    for k, p in b["prelevements"].items():
        assert [(v["destinataire"], v["part"]) for v in a["prelevements"][k]["ventilation"]] == [
            (v["destinataire"], v["part"]) for v in p["ventilation"]], k
    a, b = _fixture("prelevements/tva_conso.json"), lire("prelevements/tva_conso.json")
    assert a["tranches"] == b["tranches"] and a["deciles_niveau_de_vie"] == b["deciles_niveau_de_vie"]
    assert _fixture("prelevements/taxe_fonciere/69.json")["communes"]["69123"] == lire("prelevements/taxe_fonciere/69.json")["communes"]["69123"]
    assert _fixture("arbre/racine.json")["md"] == TOTAL_MD
    assert _fixture("deficit.json")["etat"] == lire("deficit.json")["etat"]


def test_R15b_fixtures_web_dette_egales_site():
    """Constat M2 (corrigé) : les fixtures web de dette/ sont les fichiers publiés."""
    besoin("dette/interets.json", "dette/index.json")
    for rel in ("dette/interets.json", "dette/index.json", "dette/detenteurs.json", "dette/encours.json"):
        assert _fixture(rel) == lire(rel), rel


# ---------------------------------------------------------------------------------------------------------------------
# R16-R19 Opérateurs, nature, bénéficiaires, traçabilité
# ---------------------------------------------------------------------------------------------------------------------


def _scsp(annee, champ="financement_etat"):
    s = 0.0
    for o in lire("operateurs/operateurs.json")["operateurs"]:
        a = o["annees"].get(annee) or {}
        v = ((a.get(champ) or {}).get("scsp") or {}).get("cp_eur")
        if v is not None:
            s += v
    return s


def test_R16_scsp_operateurs_inferieure_categorie_32():
    besoin("operateurs/operateurs.json", "operateurs/index.json", "nature_etat.json")
    nat = _nature()
    c32 = sum(c["eur"] for d in nat.values() for c in d["categories"] if c["code"] == "32")
    s24 = _scsp("2024")
    assert abs(lire("operateurs/index.json")["totaux"]["2024"]["scsp_cp_eur"] - s24) < 1
    assert s24 <= c32, (s24, c32)
    # LFI 2025 des opérateurs face à la catégorie 32 du PLF 2025 (vue nature, autre millésime : ordre de grandeur)
    c32_plf = next(c["md"] for t in lire("nature_etat.json")["titres"] for c in t["categories"] if c["code"] == "32")
    assert _scsp("2025", "credits_votes_lfi") / 1e9 <= c32_plf


def test_R16b_scsp_tracee_plafonnee_par_programme():
    """Traçabilité : SCSP rattachée à un programme ≤ sa catégorie 32 ramenée au montant de l'arbre (méthode de
    pipeline/tracabilite.py, plafond = part de la catégorie 32 × montant du programme dans l'arbre ; constat M4)."""
    besoin("operateurs/operateurs.json")
    nat = _nature()
    total = 0.0
    for p, (n, _, _) in PROG.items():
        f = f"tracabilite/programme_{p}.json"
        if not existe(f) or p not in nat or nat[p]["total_eur"] <= 0:
            continue
        sc = sum(c["eur"] for c in lire(f)["composantes"].get("beneficiaire_identifie", [])
                 if c.get("detail", "").startswith("Subvention pour charges de service public"))
        total += sc
        part32 = sum(x["eur"] for x in nat[p]["postes"] if x["id"] == "subventions_operateurs") / nat[p]["total_eur"]
        assert sc <= max(part32, 0) * n["md"] * 1e9 + 1, (p, sc)
    assert total <= _scsp("2024") + 1


def test_R17_nature_sommes_et_controle_arbre():
    nat = _nature()
    ecarts = []
    for p, d in nat.items():
        if abs(sum(x["eur"] for x in d["postes"]) - d["total_eur"]) > 1:
            ecarts.append((p, "postes"))
        if abs(sum(c["eur"] for c in d["categories"]) - d["total_eur"]) > 1:
            ecarts.append((p, "categories"))
        if d["total_eur"] > 0 and abs(sum(x["part_programme_pct"] for x in d["postes"]) - 100) > 0.1:
            ecarts.append((p, "pct"))
        if abs(d["eur_sur_100"] - d["total_eur"] / (TOTAL_MD * 1e9) * 100) > 1e-4:
            ecarts.append((p, "eur_sur_100"))
        ca = d["controle_arbre"]
        if p in PROG:
            if ca["total_arbre_eur"] is None or abs(ca["total_arbre_eur"] - PROG[p][0]["md"] * 1e9) > 1000:
                ecarts.append((p, "controle_arbre"))
            elif abs(ca["ecart_eur"] - (d["total_eur"] - ca["total_arbre_eur"])) > 1:
                ecarts.append((p, "ecart_eur"))
        elif ca["total_arbre_eur"] is not None:
            ecarts.append((p, "hors arbre non null"))
    assert not ecarts, ecarts[:10]
    c = lire("beneficiaires/index.json")["controle"]["nature"]
    dans = [p for p in nat if p in PROG]
    tn = sum(nat[p]["total_eur"] for p in dans)
    ta = sum(PROG[p][0]["md"] * 1e9 for p in dans)
    assert abs((tn - ta) / ta * 100 - c["ecart_global_pct"]) < 0.01
    assert abs(c["ecart_global_pct"]) <= c["tolerance_pct"]


def test_R18_beneficiaires_rattachement_arbre():
    total = TOTAL_MD * 1e9
    ecarts = []
    for f in glob.glob(str(SITE / "beneficiaires" / "programme_*.json")):
        b = json.loads(Path(f).read_text(encoding="utf-8"))
        p = b["programme"]
        if b["dans_arbre"] != (p in PROG):
            ecarts.append((p, "dans_arbre"))
        if p in PROG:
            if abs((b["programme_arbre_eur"] or 0) - PROG[p][0]["md"] * 1e9) > 1000:
                ecarts.append((p, "programme_arbre_eur"))
        elif b["programme_arbre_eur"] is not None:
            ecarts.append((p, "hors arbre non null"))
        for t in (b.get("associations") or {}).get("top", []):
            if abs(t["eur_sur_100"] - t["montant_eur"] / total * 100) > 1e-4:
                ecarts.append((p, t["siren"]))
    for t in lire("beneficiaires/france2030.json")["ensemble"]["top"]:
        if abs(t["eur_sur_100"] - t["montant_eur"] / total * 100) > 1e-4:
            ecarts.append(("france2030", t["siren"]))
    assert not ecarts, ecarts[:10]


def test_R19_tracabilite_parts_totaux_resume():
    besoin("tracabilite/resume.json")
    acc = defaultdict(float)
    ecarts = []
    progs = set()
    for f in glob.glob(str(SITE / "tracabilite" / "*.json")):
        if f.endswith("resume.json"):
            continue
        t = json.loads(Path(f).read_text(encoding="utf-8"))
        b = os.path.basename(f)
        parts = t["parts"]
        if abs(sum(x["eur"] for x in parts.values()) - t["total_eur"]) > 1:
            ecarts.append((b, "eur"))
        if abs(sum(x["pct"] for x in parts.values()) - 100) > 0.01:
            ecarts.append((b, "pct"))
        dest = next(m["pct"] for m in t["maillons"] if m["maillon"] == "destinataire")
        if abs(dest - t["taux_tracabilite_pct"]) > 0.01 or abs(t["taux_tracabilite_pct"] - (100 - parts["non_publie"]["pct"])) > 0.01:
            ecarts.append((b, "taux"))
        for k, x in parts.items():
            acc[k] += x["eur"]
            if x["eur"] != 0 and not x.get("sources"):
                ecarts.append((b, k, "sans source"))
            # seule part négative admise : un programme net négatif rangé en entier dans non_publie
            if x["eur"] < 0 and not (k == "non_publie" and t["total_eur"] < 0 and x["eur"] == t["total_eur"]):
                ecarts.append((b, k, "négatif"))
        if t["programme"]:
            progs.add(t["programme"])
            if abs(t["total_eur"] - PROG[t["programme"]][0]["md"] * 1e9) > 1000:
                ecarts.append((b, "total arbre"))
        else:
            n = _noeud(RACINE, t["id_arbre"])
            if n is None or abs(t["total_eur"] - n["md"] * 1e9) > 1000:
                ecarts.append((b, "noeud psr"))
    assert not ecarts, ecarts[:10]
    assert progs == set(PROG)
    g = lire("tracabilite/resume.json")["global"]
    assert abs(g["total_eur"] - TOTAL_MD * 1e9) < 1e4
    for k, x in g["parts"].items():
        assert abs(x["eur"] - acc[k]) < 10, k
        assert abs(x["pct"] - x["eur"] / g["total_eur"] * 100) < 0.002, k
    for gp in lire("tracabilite/resume.json")["grands_postes"]:
        n = next(c for c in RACINE["enfants"] if c["nom"] == gp["nom"])
        assert abs(gp["total_eur"] - n["md"] * 1e9) < 1e4, gp["nom"]


# ---------------------------------------------------------------------------------------------------------------------
# R20 Dépenses fiscales : nc jamais 0, totaux, rattachement aux programmes de l'arbre
# ---------------------------------------------------------------------------------------------------------------------

BRUTS_NULS = {"nc", "ε", "-", "–"}


def _niches():
    besoin("niches/mesures.json", "niches/programmes.json", "niches/index.json")
    m = lire("niches/mesures.json")
    return m, {x["id"]: x for x in m["mesures"]}, lire("niches/programmes.json"), lire("niches/index.json")


def test_R20a_niches_null_seulement_pour_nc_epsilon_tiret():
    m, _, _, _ = _niches()
    for x in m["mesures"]:
        for y, c in x["couts"].items():
            b = str(c["brut"]).strip()
            if c["meur"] is None:
                assert b in BRUTS_NULS, (x["id"], y, b)
            else:
                assert b not in BRUTS_NULS, (x["id"], y, b)


def test_R20b_niches_totaux_par_annee():
    m, _, _, idx = _niches()
    for y, t in idx["totaux"].items():
        cs = [x["couts"][y] for x in m["mesures"] if y in x["couts"] and not x["couts"][y].get("hors_reference")]
        assert abs(sum(c["meur"] for c in cs if c["meur"] is not None) - t["chiffre_meur"]) < 0.5, y
        assert len(cs) == t["mesures"] and sum(1 for c in cs if c["meur"] is not None) == t["chiffrees"], y
        assert t["mesures"] == t["chiffrees"] + t["nc"] + t["epsilon"] + t["sans_effet"], y
        if t["total_publie_meur"] is not None:
            if int(y) <= 2024:  # contrôle bloquant du contrat (2.18)
                assert abs(t["total_publie_meur"] - t["chiffre_meur"]) <= 1, y
            else:  # écart publié (prévision imputée aux « nc » par la DGFiP)
                assert abs(t["ecart_meur"] - (t["total_publie_meur"] - t["chiffre_meur"])) < 0.5, y


def test_R20c_niches_rattachement_aux_noeuds_de_l_arbre():
    m, _, pr, _ = _niches()
    ids = {n["id"]: p for p, (n, _, _) in PROG.items()}
    for x in m["mesures"]:
        p = x["programme"]
        if p is None:
            continue
        if p["noeud_arbre"] is None:
            assert p["code"] not in PROG, x["id"]
        else:
            assert ids.get(p["noeud_arbre"]) == p["code"], x["id"]
    for p in pr["programmes"]:
        n = PROG[p["programme"]][0]
        assert p["noeud"] == n["id"]
        assert abs(p["budget_meur"] - n["md"] * 1000) < 0.5, p["programme"]
    for p in pr["hors_arbre"]:
        assert p["programme"] not in PROG


def test_R20d_niches_missions_et_grands_postes_sommes_des_programmes():
    """Contrat 2.18 : missions[] et grands_postes[] = « mêmes sommes » que les programmes du fichier (constat M11 :
    budget_meur n'est donc pas le budget de la mission, seulement celui de ses programmes porteurs de mesures)."""
    _, _, pr, _ = _niches()
    for niveau, cle, champ in (("missions", "mission", "nom"), ("grands_postes", "grand_poste", "nom")):
        acc = defaultdict(lambda: [0.0, 0.0])
        for p in pr["programmes"]:
            acc[p[cle]][0] += p["budget_meur"]
            acc[p[cle]][1] += p["fiscal_meur"]["2024"] or 0  # null (non chiffré) n'ajoute rien
        for x in pr[niveau]:
            assert abs(acc[x[champ]][0] - x["budget_meur"]) < 0.5, x[champ]
            assert abs(acc[x[champ]][1] - x["fiscal_2024_meur"]) < 0.5, x[champ]
    # constat M11 (corrigé) : le budget de la mission dans l'arbre est publié à côté, et il est celui de l'arbre
    arbre_mission, arbre_gp = defaultdict(float), defaultdict(float)
    for g in RACINE["enfants"]:
        for m in g.get("enfants", []):
            for p in m.get("enfants", []):
                if p["niveau"] == "programme":
                    arbre_mission[m["nom"]] += p["md"] * 1000
                    arbre_gp[g["nom"]] += p["md"] * 1000
    for x in pr["missions"]:
        assert abs(x["budget_arbre_meur"] - arbre_mission[x["nom"]]) < 0.5, x["nom"]
        assert x["budget_arbre_meur"] >= x["budget_meur"] - 0.5, x["nom"]
    for x in pr["grands_postes"]:
        assert abs(x["budget_arbre_meur"] - arbre_gp[x["nom"]]) < 0.5, x["nom"]


def _fiscal_attendu(M, p, y):
    cs = [M[i]["couts"].get(y) for i in p["mesures"]]
    cs = [c for c in cs if c and not c.get("hors_reference")]
    ch = [c["meur"] for c in cs if c["meur"] is not None]
    return (sum(ch) if ch else None), cs


def test_R20e_niches_fiscal_programme_egale_somme_mesures():
    _, M, pr, _ = _niches()
    ecarts = []
    for p in pr["programmes"] + pr["hors_arbre"]:
        for y, v in p["fiscal_meur"].items():
            att, _ = _fiscal_attendu(M, p, y)
            if att is None or v is None:
                continue
            if abs(v - att) > 0.5:
                ecarts.append((p["programme"], y, v, att))
    assert not ecarts, ecarts


def test_R20f_niches_hors_reference_hors_totaux_des_programmes():
    """Constat I2 (corrigé) : un coût `hors_reference` n'entre dans aucune somme par programme ; il est publié à part."""
    m, M, pr, idx = _niches()
    groupes = pr["programmes"] + pr["hors_arbre"]
    for y in ("2024", "2025", "2026"):
        hors = sum(x["couts"][y]["meur"] or 0 for x in m["mesures"] if y in x["couts"] and x["couts"][y].get("hors_reference"))
        assert abs(hors - sum(g.get("hors_reference_meur", {}).get(y, 0) for g in groupes)) < 0.5, y
        s = sum(g["fiscal_meur"][y] or 0 for g in groupes)
        assert abs(s - idx["totaux"][y]["chiffre_meur"]) < 0.5, y
    p343 = next(p for p in pr["programmes"] if p["programme"] == "343")
    assert p343["fiscal_meur"]["2024"] == 0 and p343["hors_reference_meur"]["2024"] == 19
    assert abs(pr["couverture"]["rattache_arbre_meur"] - sum(p["fiscal_meur"]["2024"] or 0 for p in pr["programmes"])) < 0.5


def test_R20g_niches_programme_sans_mesure_chiffree_jamais_zero():
    """Constat I3 (corrigé) : aucune mesure chiffrée et au moins une « nc » ou « ε » : null avec la mention, jamais
    0 ; à l'inverse un null porte toujours sa mention et un montant publié a au moins une mesure chiffrée ou « - »."""
    _, M, pr, _ = _niches()
    zeros, nuls = [], 0
    for p in pr["programmes"] + pr["hors_arbre"]:
        for y, v in p["fiscal_meur"].items():
            att, cs = _fiscal_attendu(M, p, y)
            non_chiffre = att is None and any(str(c["brut"]).strip() in ("nc", "ε") for c in cs)
            if non_chiffre != (v is None):
                zeros.append((p["programme"], y, v))
            if (v is None) != (y in p.get("mention", {})):
                zeros.append((p["programme"], y, "mention"))
            nuls += v is None
    assert not zeros, zeros
    assert nuls >= 12, nuls  # les 12 couples programme-année du constat


# ---------------------------------------------------------------------------------------------------------------------
# R21-R22 Prélèvements : affectation, recettes, taxe foncière, Sécurité sociale
# ---------------------------------------------------------------------------------------------------------------------


def test_R21a_affectation_parts_et_destinataires():
    a = lire("prelevements/affectation.json")
    for k, p in a["prelevements"].items():
        if p["statut"] == "sourcee":
            assert abs(sum(v["part"] for v in p["ventilation"]) - 1) <= 1e-4 + 1e-6, k
        for v in p["ventilation"]:
            assert v["destinataire"] in a["destinataires"], (k, v["destinataire"])
            assert a["destinataires"][v["destinataire"]]["administration"] in ("Etat", "Collectivites locales", "Securite sociale")
        mts = [v.get("montant_md") for v in p["ventilation"]]
        if all(x is not None for x in mts):  # parts = montants / total
            tot = sum(mts)
            for v in p["ventilation"]:
                # montants arrondis au M€ (0,0005 Md€) : tolérance proportionnelle
                assert abs(v["part"] - v["montant_md"] / tot) <= 0.0005 / tot + 1e-6, (k, v["destinataire"])


# Constat M6 : TVA 2025 de l'affectation (PLF 2026 et PLFSS 2026, 210,0 Md€) contre Eurostat D211 (208,82 Md€).
TOL_TVA_PART_POINTS = 0.01
TOL_TVA_MONTANT_MD = 2.5


def test_R21b_tva_affectation_face_aux_recettes_eurostat():
    a = lire("prelevements/affectation.json")
    r = lire("recettes.json")["impots"]["D211"]["par_administration"]
    an = a["annee"]
    eu = {k: v[an] for k, v in r.items()}
    assert abs(sum(v for k, v in eu.items() if k != "Ensemble") - eu["Ensemble"]) < 0.05
    par_admin = defaultdict(float)
    for v in a["prelevements"]["tva"]["ventilation"]:
        par_admin[a["destinataires"][v["destinataire"]]["administration"]] += v["part"]
    for adm, part in par_admin.items():
        assert abs(part - eu[adm] / eu["Ensemble"]) <= TOL_TVA_PART_POINTS, adm
    total_aff = sum(v["montant_md"] for v in a["prelevements"]["tva"]["ventilation"])
    assert abs(total_aff - eu["Ensemble"]) <= TOL_TVA_MONTANT_MD
    t = lire("prelevements/tva_conso.json")["totaux_nationaux_2025_md"]["tva"]
    assert abs(t["md"] - eu["Ensemble"]) < 0.01  # tva_conso cite recettes.json comme source
    m = lire("meta.json")["controle"]
    assert m["tva_derniere_annee"] == eu


def test_R21c_tva_conso_deciles():
    t = lire("prelevements/tva_conso.json")
    for tr in t["tranches"]:
        d = tr["detail_eur_par_uc"]
        assert abs(sum(x["part"] for x in d.values()) - 1) < 2e-4, tr["decile"]
        assert abs(sum(x["central"] for x in d.values()) - tr["taxes_produits_eur_par_uc"]["central"]) < 0.05, tr["decile"]
        b = tr["taxes_produits_eur_par_uc"]
        assert b["bas"] <= b["central"] <= b["haut"]
    bornes = t["deciles_niveau_de_vie"]["bornes_eur_par_an"]
    assert bornes == sorted(bornes)
    for i, tr in enumerate(t["tranches"]):
        assert tr["niveau_de_vie_min_eur"] == (bornes[i - 1] if i else None)
        assert tr["niveau_de_vie_max_eur"] == (bornes[i] if i < 9 else None)


def test_R21d_taxe_fonciere_agregats_egalent_affectation():
    tf = lire("prelevements/taxe_fonciere.json")["agregats_nationaux_m"]
    for v in lire("prelevements/affectation.json")["prelevements"]["taxe_fonciere"]["ventilation"]:
        assert abs(v["montant_md"] - tf[v["destinataire"]] / 1000) < 0.001, v["destinataire"]


def test_R22a_liens_affectation_secu_existent():
    besoin("secu/index.json", "secu/arbre/racine.json")
    a = lire("prelevements/affectation.json")["destinataires"]
    liens = lire("secu/index.json")["liens_affectation"]["noeuds"]
    trouves = {}

    def w(n):
        if n.get("destinataire"):
            trouves[n["destinataire"]] = n["id"]
        for c in n.get("enfants", []):
            w(c)

    w(lire("secu/arbre/racine.json"))
    assert trouves == liens
    for d in liens:
        assert a[d]["administration"] == "Securite sociale", d


def test_R22b_tout_destinataire_secu_a_un_noeud_ou_un_motif():
    """Constat M3 (corrigé) : un destinataire Sécurité sociale de l'affectation a un nœud dans secu/, ou figure dans
    `liens_affectation.sans_noeud` avec son motif."""
    besoin("secu/index.json")
    a = lire("prelevements/affectation.json")
    la = lire("secu/index.json")["liens_affectation"]
    utilises = {v["destinataire"] for p in a["prelevements"].values() for v in p["ventilation"] if v["part"] > 0}
    sans = sorted(d for d in utilises if a["destinataires"][d]["administration"] == "Securite sociale" and d not in la["noeuds"])
    assert sans == sorted(la["sans_noeud"]), (sans, sorted(la["sans_noeud"]))
    ids = set()

    def w(n):
        ids.add(n["id"])
        for c in n.get("enfants", []):
            w(c)

    w(lire("secu/arbre/racine.json"))
    for d, x in la["sans_noeud"].items():
        assert len(x["motif"]) >= 20 and d not in la["noeuds"], d
        assert x["noeud_englobant"] is None or x["noeud_englobant"] in ids, d


def test_R22c_secu_index_egale_racines():
    besoin("secu/index.json")
    for vue, v in lire("secu/index.json")["vues"].items():
        assert abs(lire(v["fichier"])["md"] - v["total_md"]) < 1e-3, vue
        assert abs(sum(v["modes_md"].values()) - v["total_md"]) < 1e-2, vue


# ---------------------------------------------------------------------------------------------------------------------
# R23-R24 Collectivités : dotations, PSR, budgets
# ---------------------------------------------------------------------------------------------------------------------


def _dgf(annee):
    s = defaultdict(float)
    for f in glob.glob(str(SITE / "local" / "dotations" / "communes" / "*.json")):
        for c in json.loads(Path(f).read_text(encoding="utf-8"))["communes"].values():
            s["communes"] += (c["eur"].get(annee) or {}).get("dgf_totale") or 0
    for rel, cle in (("epci.json", "epci"), ("departements.json", "departements")):
        for c in lire(f"local/dotations/{rel}")[cle].values():
            s[cle] += (c["eur"].get(annee) or {}).get("dgf_totale") or 0
    return s


def test_R23_dgf_notifiee_dans_psr_collectivites():
    """La DGF (communes, EPCI, départements ; régions : fraction de TVA depuis 2018) est un prélèvement sur recettes :
    sa somme notifiée 2024 tient dans le PSR collectivités de l'arbre et en est la plus grosse part."""
    besoin("local/dotations/epci.json", "local/dotations/departements.json")
    s = _dgf("2024")
    total = sum(s.values()) / 1e9
    assert total <= PSR_COLL["md"], (total, PSR_COLL["md"])
    assert total >= 0.5 * PSR_COLL["md"], (total, PSR_COLL["md"])


TOL_DGF_LIGNES_HORS_COMPOSANTES = 0.0005  # communes et départements : lignes de la source dont le total diffère de ses composantes


def test_R24a_dgf_totale_egale_composantes():
    besoin("local/dotations/epci.json", "local/dotations/departements.json")
    n = ko = 0
    for f in glob.glob(str(SITE / "local" / "dotations" / "communes" / "*.json")):
        for c in json.loads(Path(f).read_text(encoding="utf-8"))["communes"].values():
            for v in c["eur"].values():
                g = lambda k: v.get(k) or 0  # noqa: E731
                base = g("dgf_forfaitaire") + g("dgf_dsu") + g("dgf_dsr") + g("dgf_dnp") + g("dgf_dacom")
                n += 1
                ko += abs(base - g("dgf_totale")) > 2
    for c in lire("local/dotations/epci.json")["epci"].values():
        for v in c["eur"].values():
            n += 1
            comp = (v.get("dgf_intercommunalite") or 0) + (v.get("dgf_compensation") or 0)
            # constat M5 (corrigé) : l'écart au total notifié est publié (dgf_ecart_composantes), jamais implicite
            assert (abs(comp - v["dgf_totale"]) > 2) == ("dgf_ecart_composantes" in v), c["nom"]
            assert comp + v.get("dgf_ecart_composantes", 0) == v["dgf_totale"] or abs(comp - v["dgf_totale"]) <= 2, c["nom"]
    for c in lire("local/dotations/departements.json")["departements"].values():
        for v in c["eur"].values():
            comp = sum(v.get(k) or 0 for k in ("dgf_forfaitaire", "dgf_compensation", "dgf_fonctionnement_minimale", "dgf_perequation_urbaine"))
            n += 1
            ko += abs(comp - v["dgf_totale"]) > 2
    assert ko / n <= TOL_DGF_LIGNES_HORS_COMPOSANTES, (ko, n)


def test_R24b_note_dgf_communes_nouvelles():
    """Constat M5 (corrigé) : la note dit que la dotation des communes nouvelles est hors `dgf_totale`, et les données
    le confirment pour chaque ligne qui la publie."""
    n = 0
    for f in glob.glob(str(SITE / "local" / "dotations" / "communes" / "*.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        assert "pas comprise dans dgf_totale" in d["note"] and "(+ dotations des communes nouvelles)" not in d["note"], f
        for c in d["communes"].values():
            for v in c["eur"].values():
                if v.get("dgf_commune_nouvelle"):
                    base = sum(v.get(k) or 0 for k in ("dgf_forfaitaire", "dgf_dsu", "dgf_dsr", "dgf_dnp", "dgf_dacom"))
                    n += 1
                    assert abs(v["dgf_totale"] - base) <= 2, (f, c["nom"])
    assert n > 1000, n
    assert "dgf_ecart_composantes" in lire("local/dotations/epci.json")["note"]


def test_R24c_dgf_comptes_departements_egale_dotations_notifiees():
    besoin("local/budgets/departements.json", "local/dotations/departements.json")
    b = lire("local/budgets/departements.json")
    i = b["agregats"].index("dgf")
    dot = lire("local/dotations/departements.json")["departements"]
    n = ko = 0
    for code, c in b["collectivites"].items():
        for y, vals in c["eur"].items():
            if not vals or code not in dot or vals[i] is None:
                continue
            dv = (dot[code]["eur"].get(y) or {}).get("dgf_totale")
            if not dv:  # Paris : DGF départementale notifiée nulle (collectivité à statut particulier)
                continue
            n += 1
            ko += abs(vals[i] - dv) / dv > 0.01
    assert n > 300 and ko == 0, (ko, n)


# ---------------------------------------------------------------------------------------------------------------------
# R25 Décisions : montants du PLRG identiques à ceux de realisations/ (null jamais 0)
# ---------------------------------------------------------------------------------------------------------------------

def _ecarts_decisions():
    """(écarts, nombre de valeurs comparées, programmes comparés) entre decisions/ et realisations/ (même PLRG)."""
    out, n, progs = [], 0, set()
    for f in sorted(glob.glob(str(SITE / "decisions" / "programme_*.json"))):
        p = json.loads(Path(f).read_text(encoding="utf-8"))
        rf = SITE / "realisations" / f"{p['programme']}.json"
        R = {}
        if rf.exists():
            R = {a["annee"]: a for a in json.loads(rf.read_text(encoding="utf-8"))["prevu_depense"]["annees"]}
        for y, a in p["annees"].items():
            if "source_plrg" not in a:
                continue
            for cd in ("lfi_cp", "lfr_cp", "reports_entrants_cp", "mouvements_reglementaires_plrg_cp",
                       "fonds_de_concours_plrg_cp", "ouverts_cp", "depenses_cp"):
                if a[cd] is None and cd not in a.get("valeurs_illisibles_plrg", {}):
                    out.append((p["programme"], y, cd, "null sans raison"))
            r = R.get(int(y))
            if not r:
                continue
            for cd, vr in (("depenses_cp", r.get("depense_constatee_eur")), ("lfi_cp", r.get("vote_lfi_eur")),
                           ("ouverts_cp", (r.get("ouvert_en_gestion") or {}).get("total_eur"))):
                if vr is None or a[cd] is None:
                    continue
                n += 1
                progs.add(p["programme"])
                if abs(vr - a[cd]) > 1:
                    out.append((p["programme"], y, cd, a[cd], vr))
    return out, n, progs


def test_R25a_decisions_egalent_realisations_pour_chaque_programme():
    """Constat B1 (corrigé) : LFI, crédits ouverts et dépenses de decisions/ = realisations/ à 1 € près, pour chaque
    programme et chaque année du PLRG, sans exception ; un null porte sa raison."""
    besoin("decisions/index.json", "realisations/index.json")
    e, n, progs = _ecarts_decisions()
    assert not e, e[:10]
    assert n >= 1000 and len(progs) >= 130, (n, len(progs))


def test_R25b_decisions_programme_200_2023():
    """Le cas du constat B1 : annexe 2023 en notation scientifique pour le programme 200 (« 1,37322E+11 »)."""
    besoin("decisions/programme_200.json")
    d = lire("decisions/programme_200.json")
    a = d["annees"]["2023"]
    assert a["depenses_cp"] == 137322000279.28 and a["lfi_cp"] == 127055000000.0 and a["ouverts_cp"] == 139544000000.0
    assert set(a["precision_plrg"]) == {"lfi_cp", "ouverts_cp", "depenses_cp"}
    etapes = {c["etape"]: c for c in d["chronologie"] if c["annee"] == 2023 and "url" not in c}
    assert etapes["LFI votée"]["cp"] == a["lfi_cp"] and etapes["Exécution"]["cp"] == a["depenses_cp"]
    assert "notation scientifique" in etapes["Exécution"]["precision"]


def test_R25d_decisions_chronologie_null_avec_raison():
    """Une étape de la chronologie sans montant lisible porte sa raison (null, jamais 0 muet)."""
    for f in glob.glob(str(SITE / "decisions" / "programme_*.json")):
        p = json.loads(Path(f).read_text(encoding="utf-8"))
        for c in p["chronologie"]:
            assert c["cp"] is not None or c.get("raison"), (p["programme"], c)


def test_R25c_decisions_coherence_plrg_conforme_selon_tolerance():
    besoin("decisions/coherence_plrg.json")
    c = lire("decisions/coherence_plrg.json")
    tol = c["tolerance"]
    for y, cols in c["annees"].items():
        for k, v in cols.items():
            if isinstance(v, dict) and v.get("ecart_pct") is not None:
                assert v["conforme"] == (v["ecart_pct"] <= tol["pct_par_annee"]), (y, k)
                for e in v.get("ecarts", []):
                    assert e["conforme"] == (abs(e["ecart_cp"]) <= tol["eur_par_programme"]), (y, k, e["programme"])


# ---------------------------------------------------------------------------------------------------------------------
# R26-R28 Déficit, recettes, administrations
# ---------------------------------------------------------------------------------------------------------------------


def test_R26_deficit_formules_et_meta():
    d = lire("deficit.json")
    for vue, a in d["etat"]["annees"].items():
        solde = (a["recettes_nettes_bg_md"] + a["fonds_de_concours_md"] - a["depenses_nettes_bg_md"]
                 - a["prelevements_sur_recettes_md"] + a["solde_comptes_speciaux_md"] + a["solde_budgets_annexes_md"])
        assert abs(solde - a["solde_budgetaire_md"]) < 0.01, vue
        assert abs(-a["solde_budgetaire_md"] / (a["depenses_nettes_bg_md"] + a["prelevements_sur_recettes_md"]) - a["part_empruntee"]) < 1e-4, vue
    adm = lire("administrations.json")["annees"]
    for y, a in d["administrations_publiques"]["annees"].items():
        assert a["B9_md"] == adm[y]["Ensemble"]["B9"] and a["TE_md"] == adm[y]["Ensemble"]["TE"], y
        assert abs(-a["B9_md"] / a["TE_md"] - a["part_empruntee"]) < 1e-4, y
        if y in d["solde_public"]:
            assert d["solde_public"][y] == a["B9_md"], y
    m = lire("meta.json")["controle"]
    assert m["part_empruntee_etat"] == {k: v["part_empruntee"] for k, v in d["etat"]["annees"].items()}
    y, v = m["part_empruntee_apu_derniere_annee"]
    assert d["administrations_publiques"]["annees"][y]["part_empruntee"] == v


# Constat M12 : la part empruntée de l'écran 3 a pour dénominateur dépenses nettes du budget général + PSR (dégrèvements
# d'impôts locaux compris), pas le total de l'arbre ; écart documenté dans deficit.json `etat.perimetre`.
TOL_DENOMINATEUR_PART_EMPRUNTEE_PCT = 3.0


def test_R27_ecran3_part_empruntee_et_vues_arbre():
    d = lire("deficit.json")["etat"]
    assert "degrevements" in d["perimetre"]
    for dossier in ("arbre", "arbre_lfi2025"):
        if not existe(f"{dossier}/racine.json"):
            continue
        r = lire(f"{dossier}/racine.json")
        a = d["annees"].get(r["millesime"])
        assert a is not None, f"écran 3 : pas de part empruntée pour {r['millesime']}"
        den = a["depenses_nettes_bg_md"] + a["prelevements_sur_recettes_md"]
        assert abs(den - r["md"]) / r["md"] * 100 <= TOL_DENOMINATEUR_PART_EMPRUNTEE_PCT, dossier
        # « sur 100 € » : les grands postes couvrent exactement la racine (pas de double compte entre postes)
        assert abs(sum(c["md"] for c in r["enfants"]) - r["md"]) < 1e-4


def test_R28a_methode_administrations_ecart_egale_difference():
    m = lire("arbre_administrations/methode.json")
    assert abs(m["somme_administrations_md"] - m["total_consolide_md"] - m["ecart_consolidation_md"]) < 0.15
    c = lire("meta.json")["controle"]["arbre_administrations"]
    assert abs(c["somme_md"] - c["total_consolide_s13_md"] - c["ecart_consolidation_md"]) < 0.15
    # constat I1 (corrigé) : l'écart sur les dépenses totales (TE) est publié à part, sous un autre nom
    assert m["ecart_depenses_totales_md"] == c["ecart_depenses_totales_md"] >= m["ecart_consolidation_md"]
    f = FIXT / "meta.json"
    if f.exists():  # la fixture web porte les mêmes valeurs : le test de l'écran Méthode prouve la phrase affichée
        assert json.loads(f.read_text(encoding="utf-8"))["controle"]["arbre_administrations"] == c


# Constat M13 : COFOG gov_10a_exp (1 671,8 Md€) et gov_10a_main TE (1 672,7 Md€) pour 2024, deux tables Eurostat.
TOL_COFOG_TE_MD = 1.5


def test_R28b_administrations_sommes_et_cofog():
    m = lire("arbre_administrations/methode.json")
    r = lire("arbre_administrations/racine.json")
    c = lire("cofog.json")
    assert abs(r["md"] - m["somme_administrations_md"]) < 0.06
    assert abs(c["total"] - m["total_consolide_md"]) < 0.06
    assert abs(sum(f["md"] for f in c["fonctions"]) - c["total"]) < 0.06
    te = lire("administrations.json")["annees"][c["annee"]]["Ensemble"]["TE"]
    assert abs(te - c["total"]) <= TOL_COFOG_TE_MD
    for code in ("D211", "D51A_C1", "D61"):
        pa = lire("recettes.json")["impots"][code]["par_administration"]
        for y in pa["Ensemble"]:
            s = sum(pa[a].get(y) or 0 for a in pa if a != "Ensemble")
            assert abs(s - pa["Ensemble"][y]) < 0.1, (code, y)


# ---------------------------------------------------------------------------------------------------------------------
# R29-R31 Dette (encours, détenteurs), contrôle, vie politique
# ---------------------------------------------------------------------------------------------------------------------

TOL_DETENTEURS_ENCOURS_MD = 1.0  # constat M8 : gov_10dd_ggd (détenteurs) contre edpt1 (encours), écart publié dans ecarts[]


def test_R29_detenteurs_somme_et_encours():
    besoin("dette/detenteurs.json", "dette/encours.json")
    d = lire("dette/detenteurs.json")
    y = d["derniere_annee"]
    assert abs(sum(v["part"][y] for v in d["eurostat"].values()) - 1) < 1e-3
    total = d["total_md"][y] if isinstance(d["total_md"], dict) else d["total_md"]
    assert abs(sum(v["md"][y] for v in d["eurostat"].values()) - total) < 0.2
    e = lire("dette/encours.json")
    assert abs(e["eurostat"]["S13"]["md"][y] - total) <= TOL_DETENTEURS_ENCOURS_MD
    if abs(e["eurostat"]["S13"]["md"][y] - total) >= 0.05:  # constat M8 (corrigé) : l'écart est publié
        x = [z for z in d["ecarts"] if z["annee"] == y and "encours_md" in z]
        assert len(x) == 1 and abs(x[0]["ecart_md"] - (total - e["eurostat"]["S13"]["md"][y])) < 0.06, x
    ins = e["insee"]
    for an in ins["Ensemble"]["md"]:
        s = sum((ins[k]["md"].get(an) or 0) for k in ("Etat", "ODAC", "APUL", "ASSO"))
        if all(ins[k]["md"].get(an) is not None for k in ("Etat", "ODAC", "APUL", "ASSO")):
            assert abs(s - ins["Ensemble"]["md"][an]) < 0.5, an


# Constat M7 : deux jeux Urssaf (champ Urssaf, niches/sociales ; champ large, controle/) : écart ≤ 0,5 % par an.
TOL_URSSAF_DEUX_CHAMPS = 0.005


def test_R30_controle_aides_liens_et_urssaf():
    besoin("controle/aides_entreprises.json", "niches/sociales.json")
    a = lire("controle/aides_entreprises.json")
    f = next(x for x in a["donnees_du_site"] if x["fichier"] == "beneficiaires/france2030.json")
    assert abs(f["montant_eur"] - lire("beneficiaires/france2030.json")["ensemble"]["total_eur"]) < 1
    for x in a["donnees_du_site"]:
        assert existe(x["fichier"]), x["fichier"]
    ns = lire("niches/sociales.json")["urssaf"]["totaux_meur"]
    for x in a["exonerations_cotisations_urssaf"]["annees"]:
        assert abs(sum(x["par_categorie_eur"].values()) - x["total_eur"]) < 1, x["annee"]
        y = str(x["annee"])
        if y in ns:
            assert abs(x["total_eur"] / 1e6 - ns[y]) / ns[y] <= TOL_URSSAF_DEUX_CHAMPS, y
    for e in a["estimations"]:  # estimations jamais additionnées : composantes ≤ montant publié
        if e.get("composantes_md"):
            assert sum(v for v in e["composantes_md"].values() if v is not None) <= (e.get("md_haut") or e["md"]) + 0.5


def test_R31_vie_politique_sur_100_denominateur_publie():
    """`euros_sur_100_euros_etat` a son propre dénominateur publié (budget général hors remboursements, constat M10) :
    la valeur doit s'en déduire, et le libellé du site dit « budget général »."""
    besoin("vie_politique/annees.json")
    for a in lire("vie_politique/annees.json")["annees"]:
        p = a.get("programme_232")
        if not p or p.get("euros_sur_100_euros_etat") is None:
            continue
        assert abs(p["total_actions_01_a_03_eur"] / p["denominateur_eur"] * 100 - p["euros_sur_100_euros_etat"]) < 1e-3, a["annee"]
    src = (ROOT / "web" / "src" / "ecrans" / "viepolitique.ts").read_text(encoding="utf-8")
    assert "sur 100 € du budget général" in src


# ---------------------------------------------------------------------------------------------------------------------
# R32 Absence : null jamais 0 dans les fichiers de synthèse lus par le site
# ---------------------------------------------------------------------------------------------------------------------


def test_R32_effectifs_null_propage():
    for f in glob.glob(str(SITE / "effectifs" / "*.json")):
        e = json.loads(Path(f).read_text(encoding="utf-8"))
        if e.get("etpt") is None or e.get("titre2_eur") is None:
            assert e.get("cout_moyen_par_etpt_eur") is None, f
        else:
            assert abs(e["cout_moyen_par_etpt_eur"] - e["titre2_eur"] / e["etpt"]) <= 1, f
        n = SITE / "nature" / f"{e['programme']}.json"
        if n.exists() and e.get("titre2_eur") is not None:
            t2 = sum(c["eur"] for c in json.loads(n.read_text(encoding="utf-8"))["categories"] if c["code"] in ("21", "22", "23"))
            assert abs(t2 - e["titre2_eur"]) <= 1, f


def test_R33_dette_interets_trou_est_null():
    besoin("dette/interets.json")
    for y, a in lire("dette/interets.json")["budgetaire"]["annees"].items():
        if a["statut"] == "trou":
            assert a["md"] is None and a.get("motif"), y
        else:
            assert a["md"] is not None and a["md"] > 0, y
