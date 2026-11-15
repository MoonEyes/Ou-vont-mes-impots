"""Calcule les valeurs de reference des cas types avec l'API publique OpenFisca.

Usage :
    python tests/cas_types/generer_reference.py                 # calcule et ecrit cas_types.json
    python tests/cas_types/generer_reference.py --verifier      # verifie seulement les noms de variables
    python tests/cas_types/generer_reference.py --api URL       # autre instance OpenFisca

Pour chaque cas, le salaire brut est retrouve a partir du net avant impot saisi par
iterations (le net est quasi lineaire en brut) : brut <- brut * net_cible / net_obtenu,
jusqu'a un ecart inferieur a 1 centime par mois. Tous les cas partent dans une seule
requete /calculate par iteration.

Montants ecrits : annuels 2025, en euros, positifs = montant preleve (OpenFisca renvoie
les prelevements en negatif). Si l'API ne repond pas apres 5 tentatives, le script le dit,
sort en code 2 et n'ecrit rien : aucune valeur n'est jamais fabriquee.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ICI = Path(__file__).resolve().parent
FICHIER = ICI / "cas_types.json"
API = "https://api.fr.openfisca.org/latest"
TENTATIVES = 5
ANNEE = 2025
MOIS = [f"{ANNEE}-{m:02d}" for m in range(1, 13)]
HEURES_TEMPS_PLEIN = 151.67
EFFECTIF = 50

# Variables utilisees : (entite, periode de definition) attendues, verifiees via l'API avant usage.
VARIABLES = {
    # entrees
    "salaire_de_base": ("individu", "MONTH"),
    "categorie_salarie": ("individu", "MONTH"),
    "contrat_de_travail": ("individu", "MONTH"),
    "heures_remunerees_volume": ("individu", "MONTH"),
    "effectif_entreprise": ("individu", "MONTH"),
    "date_naissance": ("individu", "ETERNITY"),
    "statut_occupation_logement": ("menage", "MONTH"),
    "caseT": ("foyer_fiscal", "YEAR"),
    # sorties individuelles (mensuelles, sommees sur l'annee)
    "salaire_net_a_payer": ("individu", "MONTH"),
    "salaire_imposable": ("individu", "MONTH"),
    "cotisations_salariales": ("individu", "MONTH"),
    "cotisations_employeur": ("individu", "MONTH"),
    "allegement_general": ("individu", "MONTH"),
    "csg_deductible_salaire": ("individu", "MONTH"),
    "csg_imposable_salaire": ("individu", "MONTH"),
    "crds_salaire": ("individu", "MONTH"),
    "taux_accident_travail": ("individu", "MONTH"),
    "versement_transport": ("individu", "MONTH"),
    # sorties du foyer fiscal (annuelles)
    "impot_revenu_restant_a_payer": ("foyer_fiscal", "YEAR"),
    "ip_net": ("foyer_fiscal", "YEAR"),
    "rni": ("foyer_fiscal", "YEAR"),
    "nbptr": ("foyer_fiscal", "YEAR"),
}
SORTIES_INDIVIDU = ["salaire_net_a_payer", "salaire_imposable", "cotisations_salariales", "cotisations_employeur",
                    "allegement_general", "csg_deductible_salaire", "csg_imposable_salaire", "crds_salaire",
                    "versement_transport"]
SORTIES_FOYER = ["impot_revenu_restant_a_payer", "ip_net", "rni", "nbptr"]
LOGEMENT = {"locataire": "locataire_vide", "proprietaire": "proprietaire", "loge_gratuitement": "loge_gratuitement"}


class ApiIndisponible(Exception):
    pass


def appel(session: requests.Session, methode: str, url: str, **kw) -> requests.Response:
    """Appel HTTP avec 5 tentatives (attente 2, 4, 8, 16 s) sur coupure reseau, 429 ou 5xx."""
    derniere = None
    for i in range(1, TENTATIVES + 1):
        try:
            r = session.request(methode, url, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                derniere = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                raise SystemExit(f"Requete refusee par OpenFisca ({r.status_code}) : {r.text[:800]}")
            else:
                return r
        except (requests.ConnectionError, requests.Timeout) as exc:
            derniere = f"{type(exc).__name__} : {exc}"
        if i < TENTATIVES:
            attente = 2 ** i
            print(f"  tentative {i}/{TENTATIVES} echouee ({derniere}), nouvel essai dans {attente} s", file=sys.stderr)
            time.sleep(attente)
    raise ApiIndisponible(f"{url} : {derniere} apres {TENTATIVES} tentatives")


def verifier_variables(session: requests.Session, api: str) -> str:
    """Verifie que chaque variable existe (/variables) et a l'entite et la periode attendues (/variable/<nom>)."""
    r = appel(session, "GET", f"{api}/variables")
    connues = r.json()
    absentes = [v for v in VARIABLES if v not in connues]
    if absentes:
        raise SystemExit(f"Variables absentes de l'API OpenFisca : {absentes}")
    for nom, (entite, periode) in VARIABLES.items():
        d = appel(session, "GET", f"{api}/variable/{nom}").json()
        if (d["entity"], d["definitionPeriod"]) != (entite, periode):
            raise SystemExit(f"{nom} : entite/periode {d['entity']}/{d['definitionPeriod']}, attendu {entite}/{periode}")
    version = r.headers.get("Country-Package-Version", "inconnue")
    print(f"{len(VARIABLES)} variables verifiees (openfisca-france {version})")
    return version


def par_mois(valeur) -> dict:
    return {m: valeur for m in MOIS}


def situation(cas: list[dict], bruts: dict[str, float]) -> dict:
    """Une seule situation OpenFisca contenant tous les cas (identifiants prefixes par le cas)."""
    individus, foyers, familles, menages = {}, {}, {}, {}
    vide_mois = {m: None for m in MOIS}
    for c in cas:
        p, cid = c["profil"], c["id"]
        adultes, enfants = [], []
        for pers in p["personnes"]:
            pid = f"{cid}_{pers['role']}"
            ind = {"date_naissance": {"ETERNITY": f"{pers.get('annee_naissance', 1985)}-06-15"}}
            if pers["statut_activite"] == "salarie_prive":
                ind.update({
                    "salaire_de_base": par_mois(bruts[pid]),
                    "categorie_salarie": par_mois("prive_cadre" if pers["cadre"] else "prive_non_cadre"),
                    "effectif_entreprise": par_mois(EFFECTIF),
                })
                tt = pers["temps_travail"]
                if tt["type"] == "temps_partiel":
                    ind["contrat_de_travail"] = par_mois("temps_partiel")
                    ind["heures_remunerees_volume"] = par_mois(round(HEURES_TEMPS_PLEIN * tt["quotite"], 2))
                for v in SORTIES_INDIVIDU + ["taux_accident_travail"]:
                    ind[v] = dict(vide_mois)
            individus[pid] = ind
            adultes.append(pid)
        for k, e in enumerate(p["foyer"]["enfants"]):
            eid = f"{cid}_enfant{k + 1}"
            individus[eid] = {"date_naissance": {"ETERNITY": f"{e['annee_naissance']}-06-15"}}
            enfants.append(eid)
        sorties_foyer = {v: {str(ANNEE): None} for v in SORTIES_FOYER}
        situ = p["foyer"]["situation"]
        if situ == "couple_union_libre":
            # Deux foyers fiscaux ; enfants rattaches au declarant1.
            foyers[f"{cid}_f1"] = {"declarants": [adultes[0]], "personnes_a_charge": enfants, **sorties_foyer}
            foyers[f"{cid}_f2"] = {"declarants": [adultes[1]], **json.loads(json.dumps(sorties_foyer))}
        else:
            foyers[f"{cid}_f1"] = {"declarants": adultes, "personnes_a_charge": enfants, **sorties_foyer}
            if situ == "parent_isole":
                foyers[f"{cid}_f1"]["caseT"] = {str(ANNEE): True}
        familles[f"{cid}_fam"] = {"parents": adultes, "enfants": enfants}
        menage = {"personne_de_reference": [adultes[0]], "enfants": enfants,
                  "statut_occupation_logement": par_mois(LOGEMENT[p["logement"]["statut"]])}
        if len(adultes) > 1:
            menage["conjoint"] = [adultes[1]]
        menages[f"{cid}_men"] = menage
    return {"individus": individus, "foyers_fiscaux": foyers, "familles": familles, "menages": menages}


def somme(d: dict) -> float:
    return sum(v for v in d.values() if v is not None)


def calculer(session: requests.Session, api: str, cas: list[dict]) -> tuple[dict, str, int, float]:
    cibles = {f"{c['id']}_{p['role']}": p["salaire_net_avant_impot_mensuel"]
              for c in cas for p in c["profil"]["personnes"] if p["statut_activite"] == "salarie_prive"}
    bruts = {pid: net * 1.30 for pid, net in cibles.items()}
    for it in range(1, 21):
        r = appel(session, "POST", f"{api}/calculate", json=situation(cas, bruts))
        res = r.json()
        ecarts = {}
        for pid, net in cibles.items():
            obtenu = somme(res["individus"][pid]["salaire_net_a_payer"]) / 12
            ecarts[pid] = obtenu - net
            bruts[pid] = bruts[pid] * net / obtenu
        ecart_max = max(abs(e) for e in ecarts.values())
        print(f"  iteration {it} : ecart max sur le net mensuel = {ecart_max:.4f} EUR")
        if ecart_max < 0.01:
            return res, r.headers.get("Country-Package-Version", "inconnue"), it, ecart_max
    raise SystemExit("Pas de convergence du brut apres 20 iterations : rien n'est ecrit.")


def extraire(cas: dict, res: dict) -> dict:
    personnes = {}
    for p in cas["profil"]["personnes"]:
        if p["statut_activite"] != "salarie_prive":
            continue
        ind = res["individus"][f"{cas['id']}_{p['role']}"]
        s = {v: somme(ind[v]) for v in SORTIES_INDIVIDU}
        brut = somme(ind["salaire_de_base"])
        csg_d, csg_i = -s["csg_deductible_salaire"], -s["csg_imposable_salaire"]
        pat_avant = -s["cotisations_employeur"]
        taux_at = [v for v in ind["taux_accident_travail"].values() if v is not None]
        personnes[p["role"]] = {k: round(v, 2) + 0.0 for k, v in {
            "salaire_brut": brut,
            "salaire_net_avant_impot": s["salaire_net_a_payer"],
            "salaire_imposable": s["salaire_imposable"],
            "cotisations_salariales": -s["cotisations_salariales"],
            "csg_deductible": csg_d,
            "csg_non_deductible": csg_i,
            "csg": csg_d + csg_i,
            "crds": -s["crds_salaire"],
            "cotisations_patronales_avant_reduction": pat_avant,
            "reduction_generale": s["allegement_general"],
            "cotisations_patronales": pat_avant - s["allegement_general"],
            "versement_mobilite": -s["versement_transport"],
        }.items()}
        personnes[p["role"]]["taux_accident_travail"] = round(max(taux_at), 6) if taux_at else None
    foyers = [f for f in res["foyers_fiscaux"] if f.startswith(cas["id"] + "_")]
    an = str(ANNEE)
    foyer = {
        "impot_revenu": 0.0 + round(sum(-res["foyers_fiscaux"][f]["impot_revenu_restant_a_payer"][an] for f in foyers), 2),
        "ip_net": round(sum(res["foyers_fiscaux"][f]["ip_net"][an] for f in foyers), 2),
        "revenu_net_imposable": round(sum(res["foyers_fiscaux"][f]["rni"][an] for f in foyers), 2),
        "nombre_de_parts": [res["foyers_fiscaux"][f]["nbptr"][an] for f in sorted(foyers)],
    }
    return {"personnes": personnes, "foyer": foyer}


def main() -> int:
    ap = argparse.ArgumentParser(description="Valeurs de reference OpenFisca des cas types")
    ap.add_argument("--api", default=API)
    ap.add_argument("--verifier", action="store_true", help="verifie seulement les noms de variables")
    args = ap.parse_args()
    doc = json.loads(FICHIER.read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers["User-Agent"] = "ou-vont-mes-impots-cas-types"
    try:
        version = verifier_variables(session, args.api)
        if args.verifier:
            return 0
        res, version_calc, iterations, ecart = calculer(session, args.api, doc["cas"])
    except ApiIndisponible as exc:
        print(f"API OpenFisca indisponible : {exc}. Aucune valeur n'a ete ecrite dans {FICHIER.name}.",
              file=sys.stderr)
        return 2
    for c in doc["cas"]:
        c["reference_openfisca"] = extraire(c, res)
    doc["reference"] = {
        "statut": "ok",
        "source": f"{args.api}/calculate",
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "country_package_version": version_calc or version,
        "iterations_inversion_net_brut": iterations,
        "ecart_max_net_mensuel_eur": round(ecart, 4),
        "unites": "euros par an, 2025 ; montants positifs = preleves",
    }
    FICHIER.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(doc['cas'])} cas ecrits dans {FICHIER.relative_to(ICI.parent.parent)} (openfisca-france {version_calc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
