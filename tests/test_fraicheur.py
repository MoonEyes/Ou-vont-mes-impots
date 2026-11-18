"""Fraîcheur des données (pipeline/fraicheur.py) : calendriers officiels, statuts, reproductibilité, fichier publié.

Sans réseau et sans entrepôt : les règles sont vérifiées sur un dépôt synthétique (tmp_path) ; le fichier publié
site/data/fraicheur/index.json est contrôlé tel qu'il est versionné.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "data"
PUBLIE = SITE / "fraicheur" / "index.json"
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "tests"))
import fraicheur as F  # noqa: E402


# --- Calendriers officiels -----------------------------------------------------------------------------------------

def test_premier_mardi_d_octobre_lolf_article_39():
    assert F.premier_mardi_octobre(2024) == date(2024, 10, 1)
    assert F.premier_mardi_octobre(2025) == date(2025, 10, 7)
    assert F.premier_mardi_octobre(2026) == date(2026, 10, 6)
    assert F.echeance("plf", 2027) == date(2026, 10, 6)   # projet de loi de finances pour 2027


def test_resultats_de_la_gestion_et_comptes_sociaux():
    assert F.echeance("plrg", 2026) == date(2027, 4, 30)   # avant le 1er mai depuis l'exécution 2022
    assert F.echeance("plrg", 2022) == date(2023, 4, 30)
    assert F.echeance("plrg", 2021) == date(2022, 5, 31)   # avant le 1er juin jusqu'à l'exécution 2021
    assert F.echeance("placss", 2026) == date(2027, 5, 31)


def test_notifications_eurostat_trois_semaines_apres_le_1er_avril_et_le_1er_octobre():
    p = F.prochaine_notification_pde
    assert p("2026-10-21", None) == date(2027, 4, 22)   # publication d'octobre : la suivante est en avril
    assert p("2026-04-21", None) == date(2026, 10, 22)
    assert p("2026-09-15", None) == date(2026, 10, 22)
    assert p(None, "2026-10-10") == date(2026, 10, 22)   # collecte avant la publication d'octobre
    assert p(None, "2026-11-15") == date(2027, 4, 22)
    assert p(None, None) is None


def test_dates_lues_sans_invention():
    assert F._jour("2026-10-21T23:00:00+0200") == "2026-10-21"
    assert F._jour("2026-10-21T23:30:00-0200") == "2026-10-22"     # UTC
    assert F._jour("Wed, 22 Apr 2026 15:20:04 GMT") == "2026-04-22"
    assert F._jour("2026-11-08 21:08") == "2026-11-08"
    for x in (None, "", "nc", "2026-13-01", 12):
        assert F._jour(x) is None
    assert F.date_longue("2026-10-06") == "6 octobre 2026" and F.date_longue("2026-05-01") == "1er mai 2026"
    assert F.date_longue(None) == "date inconnue"


def test_familles_et_editions():
    def fam(id_, **k):
        return F.famille_de({"id": id_, "dataset": k.get("dataset"), "titre": k.get("titre", "")})
    assert fam("budget_etat_vert", dataset="plf-2026-budget-vert") == ("budget_vert", "plf", 2026)
    assert fam("budget_etat_plf", dataset="plf25-depenses-2025-du-bg") == ("plf_destination_nature", "plf", 2025)
    assert fam("benef_associations_plf25") == ("jaune_associations", "plf", 2025)
    assert fam("assoc_jaune_plf2012") == ("jaune_associations", "plf", 2012)
    assert fam("niches_vm", titre="Voies et moyens tome II, PLF 2024 à 2026, notes 2011") == ("depenses_fiscales",
                                                                                             "plf", 2026)
    assert fam("etat_plr_2019") == ("resultats_gestion", "plrg", 2019)
    assert fam("secu_placss2024_annexe3") == ("placss_annexe3", "placss", 2024)
    assert fam("deficit_france") == ("deficit_dette_ue", "pde", None)
    assert fam("benef_decp") is None
    # chaque famille a un calendrier connu et des motifs compilables
    assert {cal for _f, _l, cal, _m in F.FAMILLES} <= set(F.CALENDRIERS)
    assert len({f for f, *_ in F.FAMILLES}) == len(F.FAMILLES)


def test_lexique_neutre_des_notes_reprises():
    t = F.neutraliser("PLFSS 2026 annexe 4 (niches sociales)")
    assert t == "PLFSS 2026 annexe 4 (exonérations de cotisations (souvent appelées niches sociales))"
    assert F.neutraliser(t) == t   # idempotent
    assert F.neutraliser("transferts coupes ou trop lents") == "transferts coupes ou lents"
    assert F.titre_court("Jaune PLF 2016 (lu par pipeline/associations.py)") == "Jaune PLF 2016"
    assert F.titre_court("Annexe ; collecte par pipeline/operateurs.py collecter (data/lake/etat/x/)") == "Annexe"


def test_constat_sans_adresse_de_requete():
    c = F._constat_court("acces refuse HTTP 403 sur https://exemple.fr/api?jeton=abc")
    assert c == "réponse HTTP 403" and "http" not in c
    assert F._constat_court("budget de temps epuise sur https://x (ConnectionError)") == "délai dépassé"
    assert F._constat_court("transfert interrompu 6 fois : IncompleteRead") == "connexion coupée ou transfert interrompu"


# --- Dépôt synthétique ---------------------------------------------------------------------------------------------

ETAPES = [F.Etape("base", "Base", ["arbre"], ["fetch", "transform"]),
          F.Etape("operateurs", "Opérateurs", ["operateurs"], ["operateurs"]),
          F.Etape("niches", "Dépenses fiscales et niches sociales", ["niches"], ["niches"]),
          F.Etape("fraicheur", "Fraîcheur", ["fraicheur"], ["fraicheur"]),
          F.Etape("datapackage", "Datapackage", [], ["datapackage"])]


def _ecrire(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def depot(tmp: Path) -> Path:
    """Dépôt minimal : une source par cas (à jour, en retard sur le calendrier, version plus récente, inaccessible,
    non vérifiée, édition remplacée, notification Eurostat)."""
    _ecrire(tmp / "collecte" / "catalogue.json", {
        "portails": {"economie": "https://data.economie.gouv.fr"},
        "sources": [
            {"id": "etat_jaune_operateurs_plf2025", "type": "url", "titre": "Jaune opérateurs PLF 2025",
             "url": "https://exemple.fr/j2025.pdf", "domaine": "etat", "licence": "x"},
            {"id": "etat_jaune_operateurs_plf2026", "type": "url", "titre": "Jaune opérateurs PLF 2026 ; collecte par "
             "pipeline/operateurs.py collecter", "url": "https://exemple.fr/j2026.pdf", "domaine": "etat",
             "licence": "x"},
            {"id": "niches_vm", "type": "urls", "titre": "Voies et moyens tome II, PLF 2024 à 2026, (niches sociales)",
             "urls": [{"url": "https://exemple.fr/vm.pdf", "nom": "vm.pdf"}], "domaine": "fiscalite", "licence": "x"},
            {"id": "src_ok", "type": "ods_export", "portail": "economie", "dataset": "jeu-ok", "titre": "Jeu à jour",
             "domaine": "etat", "licence": "x", "module": "pipeline/niches.py"},
            {"id": "src_refus", "type": "url", "titre": "Jeu refusé", "url": "https://exemple.fr/r.csv",
             "domaine": "etat", "licence": "x"},
            {"id": "src_muet", "type": "url", "titre": "Jeu sans trace (pipeline/operateurs.py)",
             "url": "https://exemple.fr/m.csv", "domaine": "etat", "licence": "x"},
        ],
        "non_collectables": [{"source": "Portail X", "motif": "transferts coupes ou trop lents"}],
    })
    _ecrire(tmp / "pipeline" / "sources.json", {
        "ods_base": "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets",
        "eurostat_base": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data",
        "ods": [{"id": "budget_etat_vert", "dataset": "plf-2026-budget-vert", "description": "Budget vert"},
                {"id": "situation_budgetaire", "dataset": "situations-mensuelles", "description": "Situation"}],
        "eurostat": [{"id": "deficit_france", "dataset": "gov_10dd_edpt1", "description": "Déficit", "params": {}}],
        "ods_pieces_jointes": []})
    _ecrire(tmp / "pipeline" / "entrees_lac.json", {"etapes": {
        "niches": {"sources": {"niches_vm": ["data/lake/fiscalite/niches_vm/vm.pdf"]}},
        "operateurs": {"sources": {"etat_jaune_operateurs_plf2026": [], "etat_jaune_operateurs_plf2025": []}}}})
    _ecrire(tmp / "data" / "lake" / "manifest.json", {
        "etat_jaune_operateurs_plf2025": {"collecte_le": "2026-11-15T10:00:00+00:00", "statut": "ok", "domaine": "etat",
                                          "fichiers": [{"chemin": "x", "last_modified": "Wed, 02 Oct 2024 08:00:00 GMT"}]},
        "etat_jaune_operateurs_plf2026": {"collecte_le": "2026-11-15T10:00:00+00:00", "statut": "ok", "domaine": "etat",
                                          "fichiers": [{"chemin": "y", "last_modified": None}]},
        "niches_vm": {"collecte_le": "2026-11-16T09:00:00+00:00", "statut": "ok", "domaine": "fiscalite",
                      "fichiers": []},
        "src_ok": {"collecte_le": "2026-11-17T08:00:00+00:00", "statut": "ok", "domaine": "etat", "portail": "economie",
                   "dataset": "jeu-ok", "signature_source": "2026-11-03T08:00:00+00:00|2026-11-03|2026-11-03",
                   "fichiers": []},
        "src_refus": {"collecte_le": "2026-11-17T09:00:00+00:00", "statut": "erreur", "domaine": "etat",
                      "erreur": "acces refuse HTTP 403 sur https://exemple.fr/r.csv", "fichiers": []},
    })
    _ecrire(tmp / "data" / "raw" / "budget_etat_vert.schema.json", {"modified": "2025-11-13T12:23:21+00:00"})
    _ecrire(tmp / "data" / "raw" / "situation_budgetaire.schema.json", {"modified": "2026-10-04T10:00:00+00:00"})
    _ecrire(tmp / "data" / "raw" / "deficit_france.schema.json", {"modified": "2026-10-21T11:00:00+0200"})
    _ecrire(tmp / "data" / "lake" / "_cache" / "fraicheur" / "verifications.json", {
        "budget_etat_vert": {"verifie_le": "2026-11-17T10:00:00+00:00", "statut": "ok",
                             "modifie_le": "2025-11-13T12:23:21+00:00", "constat": None},
        "situation_budgetaire": {"verifie_le": "2026-11-17T10:00:00+00:00", "statut": "ok",
                                 "modifie_le": "2026-11-04T10:00:00+00:00", "constat": None},
        "deficit_france": {"verifie_le": "2026-11-17T10:00:00+00:00", "statut": "ok",
                           "modifie_le": "2026-10-21T11:00:00+0200", "constat": None}})
    _ecrire(tmp / "site" / "data" / "mise_a_jour.json", {
        "millesime": "x", "source": "x", "genere_le": "2026-11-16T05:00:00Z", "mode": "complet",
        "etapes": [{"etape": "base", "statut": "produit", "sources_inaccessibles": []},
                   {"etape": "niches", "statut": "conserve", "sources_inaccessibles": [
                       {"commande": "pipeline/niches.py collecter", "constat": "HTTP 403 budget.gouv.fr"}]}]})
    _ecrire(tmp / "site" / "data" / "arbre" / "racine.json", {"millesime": "Exécution 2024", "source": "x"})
    _ecrire(tmp / "site" / "data" / "niches" / "index.json", {
        "millesime": "PLF 2021 à PLF 2026", "source": "x",
        "sources_inaccessibles": [{"source": "budget.gouv.fr", "constat": "HTTP 403 (niches fiscales)"}]})
    _ecrire(tmp / "site" / "data" / "operateurs" / "index.json", {
        "millesime": "Jaunes PLF 2024 à 2026", "source": "x",
        "sources": [{"id": "etat_jaune_operateurs_plf2026", "millesime": "PLF 2026"}]})
    _ecrire(tmp / ".github" / "workflows" / "data.yml",
            'on:\n  schedule:\n    - cron: "17 4 * * 1"\n'
            'run: if [ "$(date -u +%d)" -le 7 ]; then opt="--rafraichir"; fi\n'
            'run: python pipeline/tout.py ${ETAPES:+--etapes "$ETAPES"} --budget 16200\n')
    return tmp


def entrees(tmp: Path) -> F.Entrees:
    E = F.charger(depot(tmp))
    E.etapes = ETAPES
    E.date_reference = "2026-11-17"
    return E


def test_statuts_sur_un_depot_synthetique(tmp_path):
    doc = F.construire(entrees(tmp_path))
    s = {x["id"]: x for x in doc["sources"]}
    # Calendrier : PLF 2027 attendu au plus tard le 6 octobre 2026 ; seule la dernière édition collectée l'attend.
    assert s["etat_jaune_operateurs_plf2026"]["statut"] == "en_retard"
    assert s["etat_jaune_operateurs_plf2026"]["prochaine_publication"] == {
        "date": "2026-10-06", "edition": "projet de loi de finances pour 2027", "calendrier": "plf", "passee": True}
    assert s["etat_jaune_operateurs_plf2026"]["millesime_publie"] == "PLF 2026"
    assert s["etat_jaune_operateurs_plf2026"]["millesime_origine"] == "source"
    assert s["etat_jaune_operateurs_plf2025"]["prochaine_publication"] is None
    assert s["etat_jaune_operateurs_plf2025"]["statut"] == "a_jour"
    assert "l'édition 2026 de la même publication est collectée" in s["etat_jaune_operateurs_plf2025"]["explication"]
    assert s["etat_jaune_operateurs_plf2025"]["publication_source"]["date"] == "2024-10-02"
    # Base : version identique à celle de la source, mais prochaine édition passée (budget vert PLF 2027).
    assert s["budget_etat_vert"]["statut"] == "en_retard"
    assert s["budget_etat_vert"]["derniere_collecte"] == "2026-11-17"
    # Base : la source déclare une version plus récente que celle utilisée.
    assert s["situation_budgetaire"]["statut"] == "en_retard"
    assert s["situation_budgetaire"]["derniere_collecte"] is None
    assert "4 novembre 2026" in s["situation_budgetaire"]["explication"]
    # Eurostat : publication d'octobre ; la suivante en avril, pas encore passée.
    assert s["deficit_france"]["statut"] == "a_jour"
    assert s["deficit_france"]["prochaine_publication"]["date"] == "2027-04-22"
    assert s["deficit_france"]["prochaine_publication"]["passee"] is False
    # Collecte à jour sans calendrier : prochaine publication null, jamais inventée.
    assert s["src_ok"]["statut"] == "a_jour" and s["src_ok"]["prochaine_publication"] is None
    assert s["src_ok"]["publication_source"] == {"date": "2026-11-03",
                                                 "nature": "date de modification du jeu déclarée par le portail"}
    assert s["src_ok"]["etapes"] == ["niches"]
    # Refus : inaccessible, rien n'est contourné, l'adresse de la requête n'est pas recopiée.
    assert s["src_refus"]["statut"] == "inaccessible"
    assert "HTTP 403" in s["src_refus"]["explication"] and "exemple.fr" not in s["src_refus"]["explication"]
    assert s["src_refus"]["derniere_collecte"] is None and s["src_refus"]["derniere_verification"] == "2026-11-17"
    # Sans trace : non vérifiée, aucune date.
    assert s["src_muet"]["statut"] == "non_verifiee" and s["src_muet"]["derniere_collecte"] is None
    assert s["src_muet"]["etapes"] == ["operateurs"]
    # Titres et notes au lexique neutre.
    assert "souvent appelées niches sociales" in s["niches_vm"]["titre"]
    assert doc["non_collectables"] == [{"source": "Portail X", "motif": "transferts coupes ou lents"}]
    # Comptes cohérents, ordre écrit, mise à jour hebdomadaire lue dans le workflow.
    assert sum(doc["comptes"].values()) == doc["total"] == len(doc["sources"])
    assert doc["mise_a_jour_hebdomadaire"]["jour"] == "lundi" and doc["mise_a_jour_hebdomadaire"]["heure_utc"] == "04:17"
    assert doc["mise_a_jour_hebdomadaire"]["relecture_mensuelle"] is True
    assert doc["mise_a_jour_hebdomadaire"]["budget_s"] == 16200
    et = {x["etape"]: x for x in doc["etapes"]}
    assert set(et) == {"base", "operateurs", "niches"}
    assert et["niches"]["statut_passage"] == "conserve" and et["niches"]["sources_inaccessibles_passage"]
    assert et["niches"]["signalements"][0]["constat"] == "HTTP 403 (dépenses fiscales (souvent appelées niches fiscales))"
    assert et["niches"]["libelle"] == "Dépenses fiscales et exonérations de cotisations"
    assert et["base"]["millesime"] == "Exécution 2024"


def test_passage_en_cours_plus_recent_que_le_rapport(tmp_path):
    E = entrees(tmp_path)
    E.etat_passage = {"niches": {"statut": "produit", "le": "2026-11-17T06:00:00Z"},
                      "base": {"statut": "produit", "le": "2026-11-15T06:00:00Z"}}   # plus ancien : ignoré
    et = {x["etape"]: x for x in F.construire(E)["etapes"]}
    assert et["niches"]["statut_passage"] == "produit" and et["niches"]["statut_passage_origine"] == "passage_en_cours"
    assert et["niches"]["sources_inaccessibles_passage"] == []
    assert et["base"]["statut_passage_origine"] == "rapport"


def test_sans_manifeste_la_derniere_version_est_gardee(tmp_path):
    depot(tmp_path)
    (tmp_path / "data" / "lake" / "manifest.json").unlink()
    with pytest.raises(SystemExit, match="manifest.json absent"):
        F.charger(tmp_path)


def test_deux_productions_identiques_octet_pour_octet(tmp_path):
    depot(tmp_path)
    sorties = []
    for graine in ("1", "2"):
        out = tmp_path / f"sortie_{graine}"
        code = ("import sys; from pathlib import Path; sys.path.insert(0, %r); import fraicheur; "
                "fraicheur.produire(Path(%r), racine=Path(%r))" % (str(ROOT / "pipeline"), str(out), str(tmp_path)))
        env = {k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}
        r = subprocess.run([sys.executable, "-c", code], env={**env, "PYTHONHASHSEED": graine}, capture_output=True,
                           text=True, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        sorties.append((out / "index.json").read_bytes())
    assert sorties[0] == sorties[1]
    assert json.loads(sorties[0])["date_reference"] == "2026-11-17"   # dernière collecte du manifeste


# --- Fichier publié ------------------------------------------------------------------------------------------------

pytestmark_publie = pytest.mark.skipif(not PUBLIE.exists(), reason="site/data/fraicheur/index.json pas encore produit")


@pytestmark_publie
def test_fichier_publie_conforme_au_schema_et_coherent():
    sys.path.insert(0, str(ROOT / "docs"))
    import valider_contrat as vc
    doc = json.loads(PUBLIE.read_text(encoding="utf-8"))
    v = vc.validateur(vc.charger_jsonschema(), "fraicheur_index.schema.json")
    assert vc.erreurs(v, doc) == []
    assert vc.liens_fichiers(PUBLIE, doc) == []
    assert PUBLIE.stat().st_size < 1_000_000
    ids = [s["id"] for s in doc["sources"]]
    assert len(ids) == len(set(ids)) == doc["total"]
    assert {k: sum(1 for s in doc["sources"] if s["statut"] == k) for k in F.ORDRE_STATUTS} == doc["comptes"]
    connues = {e["etape"] for e in doc["mise_a_jour_hebdomadaire"]["etapes"]}
    ref = date.fromisoformat(doc["date_reference"])
    for s in doc["sources"]:
        assert set(s["etapes"]) <= connues, s["id"]
        p = s["prochaine_publication"]
        if s["statut"] == "a_jour":
            assert s["derniere_collecte"], s["id"]
            assert not (p and p["passee"]), s["id"]
        if s["statut"] == "en_retard":
            assert (p and p["passee"]) or "version modifiée le" in s["explication"], s["id"]
        if s["statut"] == "inaccessible":
            assert s["derniere_verification"] and not s["derniere_collecte"], s["id"]
        if p:
            assert p["passee"] == (date.fromisoformat(p["date"]) <= ref), s["id"]
            if p["calendrier"] == "plf":
                d = date.fromisoformat(p["date"])
                assert d.month == 10 and d.weekday() == 1 and d.day <= 7, s["id"]   # premier mardi d'octobre
        if s["millesime_publie"]:
            assert s["millesime_origine"] in ("source", "page") and s["fichier_millesime"], s["id"]


@pytestmark_publie
def test_textes_affiches_au_lexique_neutre():
    """Tout texte destiné à l'écran (titres, libellés, explications, constats) suit docs/lexique_neutre.json ; les
    identifiants, chemins et adresses ne sont pas de la rédaction."""
    import test_neutralite as tn
    doc = json.loads(PUBLIE.read_text(encoding="utf-8"))
    techniques = {"id", "etape", "etapes", "titre_etape", "sorties", "fichier", "fichier_millesime", "url", "famille",
                  "cron", "calendrier", "cles"}

    def textes(x, cle=None):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "titre" and isinstance(v, str) and "etape" in x:   # titre technique de pipeline/tout.py
                    continue
                yield from textes(v, k)
        elif isinstance(x, list):
            for v in x:
                yield from textes(v, cle)
        elif isinstance(x, str) and cle not in techniques:
            yield cle, x
    fautes = [f"{c} : {r} : {t[:100]}" for c, t in textes(doc) for r in tn.fautes(t)]
    assert not fautes, "\n".join(fautes[:20])


def test_etape_branchee_dans_tout_avant_le_datapackage():
    import tout
    ids = [e.id for e in tout.ordre()]
    if "fraicheur" not in ids:
        pytest.skip("étape « fraicheur » absente de pipeline/tout.py")
    e = tout.PAR_ID["fraicheur"]
    assert e.sorties == ("site/data/fraicheur",)
    assert ids.index("fraicheur") < ids.index("datapackage")
    autres = set(ids) - {"fraicheur", "datapackage"}
    assert autres <= set(e.deps), sorted(autres - set(e.deps))   # toutes les étapes de données passent avant
