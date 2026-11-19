"""Valeurs de reference des cas types des profils etendus (cas_types_profils.json).

Usage :
    python tests/cas_types/generer_reference_profils.py            # calcule et ecrit cas_types_profils.json
    python tests/cas_types/generer_reference_profils.py --verifier # verifie seulement les noms de variables OpenFisca

Deux sources publiques, appelees ici seulement (jamais depuis le site) :
- API OpenFisca (https://api.fr.openfisca.org) : fonctionnaires, contractuels de droit public, retraites,
  impot sur le revenu de tous les foyers, versement liberatoire, salaries (Alsace-Moselle, temps partiel, SMIC),
  apprenti sous le seuil d'exoneration ;
- API mon-entreprise de l'Urssaf (https://mon-entreprise.urssaf.fr/api/v1) : cotisations des micro-entrepreneurs
  et des apprentis, controle des salaries d'Alsace-Moselle. Meme base de regles que le site (modele-social) :
  cette source verifie l'integration, pas la regle.

Outre-mer (groupe 'outre_mer') : la commune (depcom du menage et depcom_foyer du foyer fiscal) est transmise a
OpenFisca, qui applique la reduction d'impot de l'article 197, I-3 du CGI. OpenFisca n'a pas de seuils de CSG sur les
pensions propres a l'outre-mer : un retraite d'outre-mer saisit son taux (releve de pension) et la reference transmet un
revenu fiscal de reference de metropole situe dans la meme tranche (RFR_PAR_TAUX), sans effet sur le taux lui-meme.

Corrections documentees (jamais de valeur fabriquee) :
- Alsace-Moselle : OpenFisca 175.0.45 applique 1,5 % (taux en vigueur jusqu'au 31/03/2022) ; le taux legal est
  1,3 % depuis le 01/04/2022. La reference retire 0,2 % de l'assiette aux cotisations salariales et l'ajoute au net
  et au salaire imposable ; l'impot du foyer est recalcule par OpenFisca a partir du salaire imposable corrige.

Si une API ne repond pas apres 5 tentatives, le script le dit, sort en code 2 et n'ecrit rien.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generer_reference import ANNEE, API, EFFECTIF, HEURES_TEMPS_PLEIN, LOGEMENT, MOIS, ApiIndisponible, appel, par_mois, somme  # noqa: E402

ICI = Path(__file__).resolve().parent
FICHIER = ICI / "cas_types_profils.json"
API_MON_ENTREPRISE = "https://mon-entreprise.urssaf.fr/api/v1"
AN = str(ANNEE)
ECART_TAUX_ALSACE_MOSELLE = 0.015 - 0.013  # OpenFisca 1,5 % ; droit en vigueur 1,3 %
SMIC_MENSUEL_2025 = 11.88 * 151.67

SALARIE = ["salaire_net_a_payer", "salaire_imposable", "cotisations_salariales", "cotisations_employeur", "allegement_general",
           "csg_deductible_salaire", "csg_imposable_salaire", "crds_salaire"]
PUBLIC = ["pension_salarie", "rafp_salarie", "ircantec_salarie", "pension_employeur", "rafp_employeur", "ati_atiacl",
          "ircantec_employeur", "fonds_emploi_hospitalier", "mmid_employeur", "famille", "fnal",
          "contribution_solidarite_autonomie", "vieillesse_plafonnee_salarie", "vieillesse_deplafonnee_salarie",
          "vieillesse_plafonnee_employeur", "vieillesse_deplafonnee_employeur", "mmid_salarie"]
RETRAITE = ["csg_deductible_retraite", "csg_imposable_retraite", "crds_retraite", "casa", "retraite_nette", "retraite_imposable"]
FOYER = ["impot_revenu_restant_a_payer", "ip_net", "rni", "nbptr", "microsocial"]
ENTREES = ["salaire_de_base", "categorie_salarie", "contrat_de_travail", "heures_remunerees_volume", "effectif_entreprise",
           "date_naissance", "salarie_regime_alsace_moselle", "traitement_indiciaire_brut", "primes_fonction_publique",
           "retraite_brute", "rfr", "remuneration_apprenti", "apprenti", "apprentissage_contrat_debut", "caseT",
           "indemnite_residence", "supplement_familial_traitement", "indemnite_compensatrice_csg", "mbic_impv", "mbic_imps", "mbnc_impo", "ebic_impv", "ebic_imps", "ebnc_impo", "statut_occupation_logement", "depcom", "depcom_foyer"]
CASES_MICRO = {("vente", False): "mbic_impv", ("service_bic", False): "mbic_imps", ("service_bnc", False): "mbnc_impo",
               ("vente", True): "ebic_impv", ("service_bic", True): "ebic_imps", ("service_bnc", True): "ebnc_impo"}
A_INVERSER = ("salarie_prive", "contractuel_public")
# Revenu fiscal de reference (une part, seuils de metropole 2025 d'OpenFisca) situe dans la tranche du taux saisi.
RFR_PAR_TAUX = {"exonere": 10000, "reduit": 14000, "median": 20000, "normal": 40000}


def verifier_variables(session: requests.Session) -> str:
    r = appel(session, "GET", f"{API}/variables")
    connues = r.json()
    absentes = [v for v in SALARIE + PUBLIC + RETRAITE + FOYER + ENTREES if v not in connues]
    if absentes:
        raise SystemExit(f"Variables absentes de l'API OpenFisca : {absentes}")
    version = r.headers.get("Country-Package-Version", "inconnue")
    print(f"{len(set(SALARIE + PUBLIC + RETRAITE + FOYER + ENTREES))} variables verifiees (openfisca-france {version})")
    return version


def apprenti_reference_openfisca(pers: dict) -> bool:
    """OpenFisca ne modelise que l'exoneration totale des contrats d'avant mars 2025 sous 79 % du SMIC."""
    return bool(pers["apprentissage"]["contrat_avant_mars_2025"]) and \
        pers["salaire_net_avant_impot_mensuel"] <= 0.79 * SMIC_MENSUEL_2025


def individu(cas: dict, pers: dict, bruts: dict[str, float]) -> dict:
    pid = f"{cas['id']}_{pers['role']}"
    ind: dict = {"date_naissance": {"ETERNITY": f"{pers.get('annee_naissance', 1985)}-06-15"}}
    vide = {m: None for m in MOIS}
    st = pers["statut_activite"]
    if st in A_INVERSER:
        cat = "public_non_titulaire" if st == "contractuel_public" else ("prive_cadre" if pers["cadre"] else "prive_non_cadre")
        ind.update({"salaire_de_base": par_mois(bruts[pid]), "categorie_salarie": par_mois(cat),
                    "effectif_entreprise": par_mois(EFFECTIF)})
        tt = pers.get("temps_travail") or {"type": "temps_plein"}
        if tt["type"] == "temps_partiel":
            ind["contrat_de_travail"] = par_mois("temps_partiel")
            ind["heures_remunerees_volume"] = par_mois(round(HEURES_TEMPS_PLEIN * tt["quotite"], 2))
        if cas["profil"]["residence"]["alsace_moselle"]:
            ind["salarie_regime_alsace_moselle"] = par_mois(True)
        for v in SALARIE + (PUBLIC if st == "contractuel_public" else []):
            ind[v] = dict(vide)
    elif st == "fonctionnaire":
        ind.update({"traitement_indiciaire_brut": par_mois(pers["traitement_indiciaire_brut_mensuel"]),
                    "primes_fonction_publique": par_mois(pers["primes_mensuelles"]),
                    "categorie_salarie": par_mois("public_titulaire_" + pers["versant"]),
                    # 'primes_mensuelles' du profil contient deja toutes les indemnites (residence, supplement familial,
                    # indemnite compensatrice de la hausse de la CSG) :
                    # on empeche OpenFisca d'en ajouter d'office.
                    "indemnite_residence": par_mois(0), "supplement_familial_traitement": par_mois(0),
                    "indemnite_compensatrice_csg": par_mois(0),
                    "effectif_entreprise": par_mois(EFFECTIF)})
        for v in SALARIE + PUBLIC:
            ind[v] = dict(vide)
    elif st == "retraite":
        ind["retraite_brute"] = par_mois(pers["pension_base_mensuelle"] + pers["pension_complementaire_mensuelle"])
        for v in RETRAITE:
            ind[v] = dict(vide)
    elif st == "independant":
        i = pers["independant"]
        ind[CASES_MICRO[(i["activite"], i["versement_liberatoire"])]] = {AN: i["chiffre_affaires_annuel"]}
    elif st == "apprenti" and apprenti_reference_openfisca(pers):
        ind.update({"remuneration_apprenti": par_mois(pers["salaire_net_avant_impot_mensuel"]), "apprenti": par_mois(True),
                    "apprentissage_contrat_debut": par_mois("2024-09-01"), "categorie_salarie": par_mois("prive_non_cadre"),
                    "effectif_entreprise": par_mois(EFFECTIF)})
        for v in SALARIE:
            ind[v] = dict(vide)
    return ind


def situation(cas_liste: list[dict], bruts: dict[str, float], imposables: dict[str, float] | None = None) -> dict:
    """Une seule situation OpenFisca pour tous les cas. Avec `imposables`, les salaires imposables sont fournis
    (recalcul de l'impot seul, cas d'Alsace-Moselle)."""
    individus, foyers, familles, menages = {}, {}, {}, {}
    for c in cas_liste:
        p, cid = c["profil"], c["id"]
        adultes, enfants = [], []
        for pers in p["personnes"]:
            pid = f"{cid}_{pers['role']}"
            if imposables is not None:
                individus[pid] = {"date_naissance": {"ETERNITY": f"{pers.get('annee_naissance', 1985)}-06-15"},
                                  "salaire_imposable": par_mois(round(imposables[pid] / 12, 4))}
            else:
                individus[pid] = individu(c, pers, bruts)
            adultes.append(pid)
        for k, e in enumerate(p["foyer"]["enfants"]):
            eid = f"{cid}_enfant{k + 1}"
            individus[eid] = {"date_naissance": {"ETERNITY": f"{e['annee_naissance']}-06-15"}}
            enfants.append(eid)
        sorties = {v: {AN: None} for v in FOYER}
        ff = {"declarants": adultes, "personnes_a_charge": enfants, **sorties}
        if p["foyer"]["situation"] == "parent_isole":
            ff["caseT"] = {AN: True}
        retraites = [x for x in p["personnes"] if x["statut_activite"] == "retraite"]
        if retraites:
            csg = retraites[0]["csg_pension"]
            if "taux" in csg:
                if len(p["personnes"]) > 1:
                    raise SystemExit(f"{cid} : taux de CSG saisi pour un couple, pas de RFR de reference defini")
                csg = {"revenu_fiscal_reference": RFR_PAR_TAUX[csg["taux"]], "parts": 1}
            ff["rfr"] = {str(ANNEE - 2): csg["revenu_fiscal_reference"]}
            ff["nbptr"] = {AN: None, str(ANNEE - 2): csg["parts"]}
        commune = p["residence"].get("commune_insee", "")
        if p["residence"]["zone"] == "dom":
            ff["depcom_foyer"] = {AN: commune}
        foyers[f"{cid}_f1"] = ff
        familles[f"{cid}_fam"] = {"parents": adultes, "enfants": enfants}
        menage = {"personne_de_reference": [adultes[0]], "enfants": enfants,
                  "statut_occupation_logement": par_mois(LOGEMENT[p["logement"]["statut"]])}
        if len(adultes) > 1:
            menage["conjoint"] = [adultes[1]]
        if p["residence"]["zone"] == "dom":
            menage["depcom"] = par_mois(commune)
        menages[f"{cid}_men"] = menage
    return {"individus": individus, "foyers_fiscaux": foyers, "familles": familles, "menages": menages}


def net_corrige(cas: dict, ind: dict) -> float:
    net = somme(ind["salaire_net_a_payer"])
    if cas["profil"]["residence"]["alsace_moselle"]:
        net += ECART_TAUX_ALSACE_MOSELLE * somme(ind["salaire_de_base"])
    return net


def calculer_openfisca(session: requests.Session, cas_liste: list[dict]) -> tuple[dict, str, int, float]:
    par_id = {c["id"]: c for c in cas_liste}
    cibles = {f"{c['id']}_{p['role']}": p["salaire_net_avant_impot_mensuel"]
              for c in cas_liste for p in c["profil"]["personnes"] if p["statut_activite"] in A_INVERSER}
    bruts = {pid: net * 1.28 for pid, net in cibles.items()}
    for it in range(1, 26):
        r = appel(session, "POST", f"{API}/calculate", json=situation(cas_liste, bruts))
        res = r.json()
        ecart_max = 0.0
        for pid, net in cibles.items():
            obtenu = net_corrige(par_id[pid.split("_")[0]], res["individus"][pid]) / 12
            ecart_max = max(ecart_max, abs(obtenu - net))
            bruts[pid] = bruts[pid] * net / obtenu
        print(f"  iteration {it} : ecart max sur le net mensuel = {ecart_max:.4f} EUR")
        if ecart_max < 0.01:
            return res, r.headers.get("Country-Package-Version", "inconnue"), it, ecart_max
    raise SystemExit("Pas de convergence du brut apres 25 iterations : rien n'est ecrit.")


def evaluer_mon_entreprise(session: requests.Session, situation_me: dict, expressions: dict[str, str]) -> dict:
    corps = {"situation": situation_me,
             "expressions": [{"valeur": regle, "unité": "€/an"} for regle in expressions.values()]}
    r = appel(session, "POST", f"{API_MON_ENTREPRISE}/evaluate", json=corps)
    valeurs = r.json()["evaluate"]
    out = {}
    for (nom, regle), v in zip(expressions.items(), valeurs):
        if not isinstance(v.get("nodeValue"), (int, float)):
            raise SystemExit(f"mon-entreprise : pas de valeur pour « {regle} » ({json.dumps(v, ensure_ascii=False)[:300]})")
        out[nom] = round(v["nodeValue"], 2) + 0.0
    return out


BASE_SALARIE_ME = {
    "salarié . cotisations . prévoyances . santé . montant": "0 €/mois",
    "salarié . cotisations . prévoyances . employeur . cadres": "0 €/mois",
}
EXPR_SALARIE_ME = {
    "salaire_brut": "salarié . contrat . salaire brut",
    "cotisations_salariales_csg_crds_comprises": "salarié . cotisations . salarié",
    "csg": "salarié . cotisations . CSG-CRDS . CSG",
    "csg_deductible": "salarié . cotisations . CSG-CRDS . CSG . déductible",
    "crds": "salarié . cotisations . CSG-CRDS . CRDS",
}
REPARTITION_MICRO = {"maladie_maternite": "maladie-maternité", "invalidite_deces": "invalidité-décès", "retraite_base": "retraite de base",
                     "retraite_complementaire": "retraite complémentaire", "csg_crds": "autres contributions"}


def reference_mon_entreprise(session: requests.Session, cas: dict, pers: dict) -> dict | None:
    st = pers["statut_activite"]
    if st == "independant":
        i = pers["independant"]
        nature = {"vente": "commerciale", "service_bic": "commerciale", "service_bnc": "libérale"}[i["activite"]]
        if i.get("artisan"):
            nature = "artisanale"
        s = {"date": f"01/06/{ANNEE}", "entreprise . catégorie juridique": "'EI'",
             "entreprise . catégorie juridique . EI . auto-entrepreneur": "oui",
             "entreprise . activité . nature": f"'{nature}'",
             "dirigeant . auto-entrepreneur . chiffre d'affaires": f"{i['chiffre_affaires_annuel']} €/an",
             "dirigeant . auto-entrepreneur . impôt . versement libératoire": "oui" if i["versement_liberatoire"] else "non"}
        if i["activite"] != "service_bnc":
            s["entreprise . activités . service ou vente"] = "'vente'" if i["activite"] == "vente" else "'service'"
        racine = "dirigeant . auto-entrepreneur . cotisations et contributions"
        expr = {"cotisations_et_contributions": racine, "cotisations": racine + " . cotisations",
                "formation_professionnelle": racine + " . CFP", "taxe_chambre_consulaire": racine + " . TFC",
                **{k: f"{racine} . cotisations . répartition . {v}" for k, v in REPARTITION_MICRO.items()}}
        if i["versement_liberatoire"]:
            expr["versement_liberatoire"] = "dirigeant . auto-entrepreneur . impôt . versement libératoire . montant"
        return evaluer_mon_entreprise(session, s, expr)
    if st == "apprenti" or (st == "salarie_prive" and cas["profil"]["residence"]["alsace_moselle"]):
        s = {**BASE_SALARIE_ME, "salarié . contrat . statut cadre": "oui" if pers.get("cadre") else "non"}
        net_annuel = 12 * pers["salaire_net_avant_impot_mensuel"]
        if st == "apprenti":
            # modele-social distingue les contrats par la date de simulation (seuil de 79 % avant mars 2025, 50 % apres).
            s["date"] = f"01/02/{ANNEE}" if pers["apprentissage"]["contrat_avant_mars_2025"] else f"01/06/{ANNEE}"
            s["salarié . contrat"] = "'apprentissage'"
            # L'inversion net -> brut de publicodes echoue quand le net egale le brut (exoneration totale) :
            # on cherche le brut ici, par iterations sur des evaluations a brut fixe.
            brut = net_annuel
            for _ in range(30):
                v = evaluer_mon_entreprise(session, {**s, "salarié . contrat . salaire brut": f"{brut} €/an"}, EXPR_SALARIE_ME)
                net = brut - v["cotisations_salariales_csg_crds_comprises"]
                if abs(net - net_annuel) < 0.05:
                    break
                brut += net_annuel - net
            else:
                raise SystemExit(f"{cas['id']} : pas de convergence du brut de l'apprenti")
        else:
            s["date"] = f"01/06/{ANNEE}"
            s["salarié . régimes spécifiques . alsace moselle"] = "oui"
            s["salarié . rémunération . net . à payer avant impôt"] = f"{pers['salaire_net_avant_impot_mensuel']} €/mois"
            v = evaluer_mon_entreprise(session, s, EXPR_SALARIE_ME)
        v["cotisations_salariales"] = round(v.pop("cotisations_salariales_csg_crds_comprises") - v["csg"] - v["crds"], 2)
        v["csg_non_deductible"] = round(v["csg"] - v["csg_deductible"], 2)
        return v
    return None


def arrondir(d: dict) -> dict:
    return {k: (round(v, 2) + 0.0 if isinstance(v, (int, float)) else v) for k, v in d.items()}


def extraire_personne(cas: dict, pers: dict, ind: dict) -> dict | None:
    st = pers["statut_activite"]
    s = {v: somme(ind[v]) for v in SALARIE + PUBLIC + RETRAITE if v in ind}
    if st in A_INVERSER or st == "fonctionnaire" or (st == "apprenti" and apprenti_reference_openfisca(pers)):
        if st == "fonctionnaire":
            brut = 12 * (pers["traitement_indiciaire_brut_mensuel"] + pers["primes_mensuelles"])
        elif st == "apprenti":
            brut = somme(ind["remuneration_apprenti"])
        else:
            brut = somme(ind["salaire_de_base"])
        correction = ECART_TAUX_ALSACE_MOSELLE * brut if cas["profil"]["residence"]["alsace_moselle"] else 0.0
        csg_d, csg_i = -s["csg_deductible_salaire"], -s["csg_imposable_salaire"]
        avant = -s["cotisations_employeur"]
        out = {
            "salaire_brut": brut,
            "salaire_net_avant_impot": s["salaire_net_a_payer"] + correction,
            "salaire_imposable": s["salaire_imposable"] + correction,
            "cotisations_salariales": -s["cotisations_salariales"] - correction,
            "csg_deductible": csg_d, "csg_non_deductible": csg_i, "csg": csg_d + csg_i, "crds": -s["crds_salaire"],
            "cotisations_patronales_avant_reduction": avant,
            "reduction_generale": s["allegement_general"],
            "cotisations_patronales": avant - s["allegement_general"],
        }
        if correction:
            out["correction_taux_alsace_moselle"] = correction
            out["cotisation_regime_local"] = -s.get("mmid_salarie", 0.0) - correction if "mmid_salarie" in s else 0.013 * brut
        if st == "fonctionnaire":
            out.update({"traitement_indiciaire_brut": 12 * pers["traitement_indiciaire_brut_mensuel"],
                        "primes": 12 * pers["primes_mensuelles"]})
        if st in ("fonctionnaire", "contractuel_public"):
            out["detail"] = arrondir({k: -s[k] for k in PUBLIC if abs(s[k]) > 0.005})
        return arrondir(out)
    if st == "retraite":
        csg_d, csg_i = -s["csg_deductible_retraite"], -s["csg_imposable_retraite"]
        return arrondir({"retraite_brute": somme(ind["retraite_brute"]), "csg_deductible": csg_d, "csg_non_deductible": csg_i,
                         "csg": csg_d + csg_i, "crds": -s["crds_retraite"], "casa": -s["casa"],
                         "retraite_nette": s["retraite_nette"], "retraite_imposable": s["retraite_imposable"]})
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Valeurs de reference des cas types des profils etendus")
    ap.add_argument("--verifier", action="store_true", help="verifie seulement les noms de variables OpenFisca")
    args = ap.parse_args()
    doc = json.loads(FICHIER.read_text(encoding="utf-8"))
    cas_liste = doc["cas"]
    session = requests.Session()
    session.headers["User-Agent"] = "ou-vont-mes-impots-cas-types"
    try:
        version = verifier_variables(session)
        if args.verifier:
            return 0
        res, version_calc, iterations, ecart = calculer_openfisca(session, cas_liste)
        references = {}
        for c in cas_liste:
            personnes, me = {}, {}
            for pers in c["profil"]["personnes"]:
                ref = extraire_personne(c, pers, res["individus"][f"{c['id']}_{pers['role']}"])
                if ref is not None:
                    personnes[pers["role"]] = ref
                v = reference_mon_entreprise(session, c, pers)
                if v is not None:
                    me[pers["role"]] = v
            references[c["id"]] = (personnes, me)
        # Alsace-Moselle : impot recalcule a partir du salaire imposable corrige.
        am = [c for c in cas_liste if c["profil"]["residence"]["alsace_moselle"]]
        ir_am = {}
        if am:
            imposables = {f"{c['id']}_{r}": v["salaire_imposable"] for c in am for r, v in references[c["id"]][0].items()}
            res_am = appel(session, "POST", f"{API}/calculate", json=situation(am, {}, imposables)).json()
            ir_am = {c["id"]: res_am["foyers_fiscaux"][f"{c['id']}_f1"] for c in am}
    except ApiIndisponible as exc:
        print(f"API indisponible : {exc}. Aucune valeur n'a ete ecrite dans {FICHIER.name}.", file=sys.stderr)
        return 2
    for c in cas_liste:
        personnes, me = references[c["id"]]
        ff = ir_am.get(c["id"]) or res["foyers_fiscaux"][f"{c['id']}_f1"]
        apprentis_hors_openfisca = any(p["statut_activite"] == "apprenti" and not apprenti_reference_openfisca(p)
                                       for p in c["profil"]["personnes"])
        foyer = {"impot_revenu": None if apprentis_hors_openfisca else 0.0 + round(-ff["impot_revenu_restant_a_payer"][AN], 2),
                 "revenu_net_imposable": None if apprentis_hors_openfisca else round(ff["rni"][AN], 2),
                 "nombre_de_parts": ff["nbptr"][AN],
                 "versement_liberatoire": round(ff["microsocial"][AN], 2)}
        sources = (["openfisca"] if personnes or not apprentis_hors_openfisca else []) + (["mon-entreprise"] if me else [])
        c["reference"] = {"sources": sources, "personnes": personnes, "mon_entreprise": me, "foyer": foyer}
    doc["reference"] = {
        "statut": "ok",
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "openfisca": {"source": f"{API}/calculate", "country_package_version": version_calc or version,
                      "iterations_inversion_net_brut": iterations, "ecart_max_net_mensuel_eur": round(ecart, 4),
                      "hypotheses": "effectif 50, pas de versement mobilite, taux AT-MP par defaut ; salaires constants sur 12 mois"},
        "mon_entreprise": {"source": f"{API_MON_ENTREPRISE}/evaluate",
                           "note": "meme base de regles que le site (modele-social) : verifie l'integration, pas la regle"},
        "corrections": [{"profil": "alsace_moselle",
                         "texte": "taux du regime local ramene de 1,5 % (OpenFisca) a 1,3 % (droit en vigueur depuis le 01/04/2022)",
                         "ecart_de_taux": ECART_TAUX_ALSACE_MOSELLE}],
        "unites": "euros par an, 2025 ; montants positifs = preleves",
    }
    FICHIER.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cas_liste)} cas ecrits dans {FICHIER.relative_to(ICI.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
