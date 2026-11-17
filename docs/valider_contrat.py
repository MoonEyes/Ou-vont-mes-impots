"""Valide les fichiers de site/data contre le contrat d'interface (docs/schemas/*.schema.json).

Usage :
    python docs/valider_contrat.py            # tous les fichiers
    python docs/valider_contrat.py --quiet    # n'affiche que les erreurs et le bilan
    python docs/valider_contrat.py --strict   # un fichier JSON couvert par aucun schema est une erreur

Controles : JSON Schema (docs/schemas/, references croisees via commun.schema.json), puis hors schema :
liens `fichier` des arbres et des index, conservation des groupes de beneficiaires (a 1 euro pres),
sommes de parts des prelevements (= 1).

Code de sortie : 0 si tout fichier present est conforme ; 1 si un fichier present est
non conforme ou si un fichier marque "existant" manque. Un fichier "prevu" absent est
signale (PREVU) sans faire echouer la validation ; un fichier orphelin (aucun schema) est
signale (ORPHELIN), bloquant seulement avec --strict.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"
SCHEMAS = Path(__file__).resolve().parent / "schemas"
EXEMPLES = Path(__file__).resolve().parent / "exemples"

# (schema, motif relatif a site/data, etat attendu). Tout fichier JSON de site/data doit etre couvert par au
# moins un motif : un fichier orphelin fait echouer la validation (contrat a completer).
FICHIERS = [
    ("meta.schema.json", "meta.json", "existant"),
    ("sankey_etat.schema.json", "sankey_etat*.json", "existant"),
    ("nature_etat.schema.json", "nature_etat.json", "existant"),
    ("arbre_etat.schema.json", "arbre/*.json", "existant"),
    ("arbre_etat.schema.json", "arbre_lfi2025/*.json", "existant"),
    ("arbre_etat.schema.json", "arbre_plf2025_nature/*.json", "existant"),
    ("programme.schema.json", "programmes/*.json", "existant"),
    ("arbre_administrations.schema.json", "arbre_administrations/racine.json", "existant"),
    ("arbre_administrations_methode.schema.json", "arbre_administrations/methode.json", "existant"),
    ("administrations.schema.json", "administrations.json", "existant"),
    ("recettes.schema.json", "recettes.json", "existant"),
    ("cofog.schema.json", "cofog.json", "existant"),
    ("deficit.schema.json", "deficit.json", "existant"),
    ("communes.schema.json", "communes/*.json", "existant"),
    # contrat 1.1 : precision par programme (pipeline/beneficiaires.py)
    ("nature_programme.schema.json", "nature/[0-9]*.json", "existant"),
    ("effectifs.schema.json", "effectifs/[0-9]*.json", "existant"),
    ("beneficiaires_programme.schema.json", "beneficiaires/programme_*.json", "existant"),
    ("france2030.schema.json", "beneficiaires/france2030.json", "existant"),
    ("marches_etat.schema.json", "beneficiaires/marches_etat.json", "existant"),
    ("beneficiaires_index.schema.json", "beneficiaires/index.json", "existant"),
    # contrat 1.2 : realisations (pipeline/realisations.py)
    ("realisations.schema.json", "realisations/[0-9]*.json", "existant"),
    ("realisations_index.schema.json", "realisations/index.json", "existant"),
    # contrat 1.3 : vie politique (pipeline/vie_politique.py)
    ("vie_politique_annees.schema.json", "vie_politique/annees.json", "existant"),
    ("vie_politique_partis.schema.json", "vie_politique/partis/*.json", "existant"),
    ("vie_politique_scrutin.schema.json", "vie_politique/scrutins/*.json", "existant"),
    ("vie_politique_candidats.schema.json", "vie_politique/candidats/*.json", "existant"),
    # contrat 1.4 : prelevements hors bulletin et affectation (pipeline/prelevements.py)
    ("prelevements_affectation.schema.json", "prelevements/affectation.json", "existant"),
    ("prelevements_tva_conso.schema.json", "prelevements/tva_conso.json", "existant"),
    ("prelevements_taxe_fonciere.schema.json", "prelevements/taxe_fonciere.json", "existant"),
    ("prelevements_taxe_fonciere_dep.schema.json", "prelevements/taxe_fonciere/*.json", "existant"),
    ("affectation_prelevements.schema.json", "affectation_prelevements.json", "prevu"),
    # traçabilité et décisions (pipeline/tracabilite.py, pipeline/decisions.py)
    ("tracabilite_noeud.schema.json", "tracabilite/programme_*.json", "existant"),
    ("tracabilite_noeud.schema.json", "tracabilite/noeud_*.json", "existant"),
    ("tracabilite_resume.schema.json", "tracabilite/resume.json", "existant"),
    ("decisions_programme.schema.json", "decisions/programme_*.json", "existant"),
    ("decisions_amendements_resume.schema.json", "decisions/amendements_resume.json", "existant"),
    ("decisions_scrutins.schema.json", "decisions/scrutins.json", "existant"),
    ("decisions_mouvements.schema.json", "decisions/mouvements_*.json", "existant"),
    ("decisions_coherence_plrg.schema.json", "decisions/coherence_plrg.json", "existant"),
    ("decisions_index.schema.json", "decisions/index.json", "existant"),
]

# Arbres decoupes : le controle des liens 'fichier' s'applique a ces schemas
SCHEMAS_ARBRE = {"arbre_etat.schema.json", "arbre_administrations.schema.json"}

# Exemples du contrat du module de calcul (docs/exemples/<prefixe>*.json)
EXEMPLES_SCHEMAS = [("profil.schema.json", "profil_*.json"), ("resultat.schema.json", "resultat_*.json")]


def charger_jsonschema():
    try:
        importlib.import_module("referencing")
        return importlib.import_module("jsonschema")
    except ImportError:
        print("jsonschema absent : installation (pip install jsonschema)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "jsonschema>=4.18"])
        importlib.invalidate_caches()
        return importlib.import_module("jsonschema")


def best_match(erreurs_):
    from jsonschema.exceptions import best_match as bm
    return bm(erreurs_)


_REGISTRE = None


def registre():
    """Tous les schemas de docs/schemas, indexes par $id (references croisees, ex. commun.schema.json)."""
    global _REGISTRE
    if _REGISTRE is None:
        from referencing import Registry, Resource
        ressources = []
        for p in sorted(SCHEMAS.glob("*.schema.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            ressources.append((doc["$id"], Resource.from_contents(doc)))
        _REGISTRE = Registry().with_resources(ressources)
    return _REGISTRE


def validateur(js, nom_schema: str):
    schema = json.loads((SCHEMAS / nom_schema).read_text(encoding="utf-8"))
    cls = js.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, registry=registre(), format_checker=cls.FORMAT_CHECKER)


def erreurs(v, doc, limite: int = 5) -> list[str]:
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        if e.context:  # oneOf / anyOf : montrer l'erreur la plus precise
            e = best_match(e.context)
        chemin = "/" + "/".join(str(p) for p in e.absolute_path)
        out.append(f"{chemin} : {e.message[:200]}")
        if len(out) >= limite:
            out.append("...")
            break
    return out


def liens_arbre(chemin: Path, doc: dict) -> list[str]:
    """Controle hors schema : chaque 'fichier' reference par un noeud existe."""
    manquants = []

    def parcourir(n):
        if "fichier" in n and not (SITE / n["fichier"]).exists():
            manquants.append(f"{n['id']} -> {n['fichier']} introuvable")
        for e in n.get("enfants", []):
            parcourir(e)

    parcourir(doc)
    return manquants


def liens_fichiers(chemin: Path, doc) -> list[str]:
    """Controle hors schema : toute cle `fichier*` qui designe un .json pointe vers un fichier present.

    Regle commune : chemin relatif a site/data/. Exception tolere (signalee au contrat) : vie_politique/annees.json
    ecrit ses liens relatifs a son propre dossier.
    """
    manquants = []

    def parcourir(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if (k.startswith("fichier") and isinstance(x, str) and x.endswith(".json") and "<" not in x):
                    if not ((SITE / x).exists() or (chemin.parent / x).exists()):
                        manquants.append(f"lien {k} -> {x} introuvable")
                else:
                    parcourir(x)
        elif isinstance(v, list):
            for x in v:
                parcourir(x)

    parcourir(doc)
    return manquants[:5]


def conservation_groupes(doc) -> list[str]:
    """Controle hors schema : dans un groupe de beneficiaires, top + autres + exclus = total (a 1 euro pres)."""
    ecarts = []

    def parcourir(v, chemin):
        if isinstance(v, dict):
            if "top" in v and "exclus_personnes_physiques_ou_non_identifies" in v:
                total = v.get("total_eur", v.get("total_source_eur"))
                somme = (sum(t["montant_eur"] for t in v["top"]) + v["autres_personnes_morales"]["montant_eur"]
                         + v["autres_non_verifies"]["montant_eur"]
                         + v["exclus_personnes_physiques_ou_non_identifies"]["montant_eur"])
                if total is None or abs(somme - total) > 1:
                    ecarts.append(f"{chemin or '/'} : conservation rompue (somme {somme:.2f} != total {total})")
            for k, x in v.items():
                parcourir(x, f"{chemin}/{k}")

    parcourir(doc, "")
    return ecarts


def sommes_de_parts(nom_schema: str, doc) -> list[str]:
    """Controle hors schema : parts d'un prelevement source (affectation) et parts communales (taxe fonciere) = 1."""
    ecarts = []
    if nom_schema == "prelevements_affectation.schema.json":
        for pid, pr in doc["prelevements"].items():
            somme = sum(v["part"] for v in pr["ventilation"])
            if pr["statut"] == "sourcee" and abs(somme - 1) > 1e-4:
                ecarts.append(f"/prelevements/{pid} : somme des parts {somme:.6f} != 1")
            for v in pr["ventilation"]:
                if v["destinataire"] not in doc["destinataires"]:
                    ecarts.append(f"/prelevements/{pid} : destinataire inconnu {v['destinataire']}")
    elif nom_schema == "prelevements_taxe_fonciere_dep.schema.json":
        for code, v in doc["communes"].items():
            if v is not None and abs(sum(v[6:12]) - 1) > 1e-3:
                ecarts.append(f"/communes/{code} : parts 6 a 11 = {sum(v[6:12]):.4f} != 1")
    return ecarts[:5]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="un fichier de site/data couvert par aucun schema fait echouer la validation")
    args = ap.parse_args()
    js = charger_jsonschema()

    n_ok = n_ko = n_prevus = n_manquants = 0
    couverts: set[Path] = set()
    for nom_schema, motif, etat in FICHIERS:
        v = validateur(js, nom_schema)
        chemins = sorted(Path(p) for p in glob.glob(str(SITE / motif)))
        couverts.update(chemins)
        if not chemins:
            if etat == "prevu":
                n_prevus += 1
                print(f"PREVU    {motif} : absent (schema {nom_schema} pret)")
            else:
                n_manquants += 1
                print(f"MANQUANT {motif} : fichier attendu absent")
            continue
        ko_motif = 0
        for p in chemins:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"KO       {p.relative_to(ROOT)} : JSON illisible ({exc})")
                ko_motif += 1
                continue
            errs = erreurs(v, doc)
            if nom_schema in SCHEMAS_ARBRE:
                errs += liens_arbre(p, doc)
            elif not errs:
                errs += liens_fichiers(p, doc) + conservation_groupes(doc) + sommes_de_parts(nom_schema, doc)
            if errs:
                ko_motif += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
        n_ko += ko_motif
        n_ok += len(chemins) - ko_motif
        if not args.quiet and not ko_motif:
            print(f"OK       {motif} ({len(chemins)} fichier{'s' if len(chemins) > 1 else ''})")

    orphelins = sorted(set(SITE.rglob("*.json")) - couverts)
    for p in orphelins[:10]:
        print(f"ORPHELIN {p.relative_to(ROOT)} : aucun schema ne couvre ce fichier (completer FICHIERS)")
    if len(orphelins) > 10:
        print(f"ORPHELIN ... et {len(orphelins) - 10} autres")

    for nom_schema, motif in EXEMPLES_SCHEMAS:
        v = validateur(js, nom_schema)
        for p in sorted(EXEMPLES.glob(motif)):
            errs = erreurs(v, json.loads(p.read_text(encoding="utf-8")))
            if errs:
                n_ko += 1
                print(f"KO       {p.relative_to(ROOT)}")
                for e in errs:
                    print(f"           {e}")
            else:
                n_ok += 1
                if not args.quiet:
                    print(f"OK       {p.relative_to(ROOT)}")

    print(f"\nBilan : {n_ok} conformes, {n_ko} non conformes, {n_manquants} manquants, {n_prevus} prevus absents, "
          f"{len(orphelins)} orphelins{' (bloquants : --strict)' if args.strict else ''}")
    return 1 if (n_ko or n_manquants or (args.strict and orphelins)) else 0


if __name__ == "__main__":
    sys.exit(main())
