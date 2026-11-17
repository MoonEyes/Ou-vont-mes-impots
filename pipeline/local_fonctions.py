"""« Pres de chez moi » : ce que chaque commune, intercommunalite et region depense par fonction (ecoles, voirie,
culture, sport...), d'apres les balances comptables de la DGFiP avec la presentation croisee nature-fonction.

Entree : data.economie.gouv.fr, jeux « Balances comptables des collectivites et des etablissements publics locaux avec
la presentation croisee nature-fonction » 2023, 2024, 2025 (DGFiP, plusieurs Go chacun). Rien n'est telecharge en
entier : trois exports agreges cote serveur par exercice (API Explore v2.1, `group_by` siren x fonction, budget
principal), quelques Mo chacun, mis en cache dans data/lake/_cache/local/fonctions/.
Reference (fichiers deja produits par pipeline/local.py, versionnes) : site/data/local/geo/<dep>.json (communes,
EPCI), budgets/communes/<dep>.json, budgets/epci/<dep>.json, budgets/regions.json (population OFGL par exercice).

Methode (formules publiees par l'OFGL, « Methodologie OFGL - Formules des agregats financiers », communes M57) :
  fonctionnement = DN6 - DN675 - DN676 - DN68 - DN65882   (DN = debit net : operations budgetaires debit - credit)
  investissement hors remboursements = D102 + D13 + D20 + D21 + D23 + D26 + D27 + D454 + D455 + D458 + D481
                   - D1027 - D10229 - D139 - D269 - D279 - D2768 - C236 - C237 - C238
appliquees ligne par ligne, puis regroupees par code de fonction (niveau 1 = 1er caractere, niveau 2 = 2 premiers).
Une ligne sans code de fonction va dans `non_ventile`. Budget principal seulement.

Communes sans presentation par fonction (facultative sous 3 500 habitants) : publiees avec le statut `non_publie`,
aucune estimation (aucune methode d'estimation publiee par une source officielle).

Sorties (site/data/local/fonctions/) :
  <dep>.json     communes du departement (toutes, avec leur statut) et EPCI dont le siege est dans le departement
  regions.json   regions et collectivites territoriales uniques
  index.json     nomenclatures, themes, couverture, et par commune un masque (1 commune, 2 EPCI, 4 region)

Commandes :
  python pipeline/local_fonctions.py            # (ou : python pipeline/local.py fonctions)
  python pipeline/local_fonctions.py --rafraichir   # retelecharge les extraits
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import local
from reproductible import date_sources

OUT = local.OUT / "fonctions"
CACHE = local.CACHE / "fonctions"
ECO = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
DATASETS = {  # exercice -> jeu DGFiP (presentation croisee nature-fonction)
    "2023": "balances-comptables-des-collectivites-et-des-epl-avec-fonction-2023",
    "2024": "balances-comptables-des-collectivites-et-des-etablissements-publics-locaux-avec-la-presentation-croisee-nature-fonction-2024",
    "2025": "balances-comptables-des-collectivites-et-des-etablissements-publics-locaux-avec-la-presentation-croisee-nature-fonction-2025",
}
CATEGS = {"Commune": "commune", "PARIS": "commune", "GFP": "epci", "ML": "epci", "REG": "region", "CTU": "region"}
SOURCE = ("data.economie.gouv.fr, DGFiP « Balances comptables des collectivites et des etablissements publics locaux "
          "avec la presentation croisee nature-fonction » {annees} (budget principal, agrege cote serveur)")


def _ou(prefixes) -> str:
    return "(" + " or ".join(f'startswith(compte,"{p}")' for p in prefixes) + ")"


def _sauf(prefixes) -> str:
    return " and ".join(f'not startswith(compte,"{p}")' for p in prefixes)


# Trois extraits par exercice : (nom, filtre sur les comptes, colonne retenue, signe)
FORMULES = {
    "fonctionnement": (f'startswith(compte,"6") and {_sauf(["675", "676", "68", "65882"])}', "d-c", 1),
    "investissement_debit": (f'{_ou(["102", "13", "20", "21", "23", "26", "27", "454", "455", "458", "481"])} and '
                             f'{_sauf(["1027", "10229", "139", "269", "279", "2768"])}', "d", 1),
    "investissement_avances": (_ou(["236", "237", "238"]), "c", -1),
}
METHODE = (
    "Depenses reelles du budget principal, comptes de l'exercice (balances DGFiP). Fonctionnement = DN6 - DN675 - "
    "DN676 - DN68 - DN65882 (debit net : debits moins annulations). Investissement hors remboursements d'emprunts = "
    "D102 + D13 + D20 + D21 + D23 + D26 + D27 + D454 + D455 + D458 + D481 - D1027 - D10229 - D139 - D269 - D279 - "
    "D2768 - C236 - C237 - C238. Formules de l'OFGL (agregats « Depenses de fonctionnement » et « Depenses "
    "d'investissement hors remb »), appliquees a chaque code de fonction. Niveau 1 = premier caractere du code, "
    "niveau 2 = deux premiers caracteres. Budgets votes par fonction : chapitres 90<f> et 93<f> lus comme la "
    "fonction <f>, chapitres 92x, 94x et 95x (operations non ventilees) rattaches a 01. Les budgets annexes (eau, assainissement, lotissements...) ne sont pas "
    "inclus. Les montants de la commune, de son intercommunalite et de sa region ne s'additionnent pas : chacun "
    "finance ses propres competences et une subvention de l'un a l'autre serait comptee deux fois.")
NON_PUBLIE = ("Presentation par fonction non publiee par la commune pour cet exercice : elle est facultative pour les "
              "communes de moins de 3 500 habitants. Aucune estimation n'est faite (aucune methode d'estimation "
              "publiee par une source officielle).")

# Libelles officiels. M57 : niveau 1 de pipeline/local.py ; niveau 2 tel que publie par l'OFGL (presentation
# fonctionnelle des departements). M14 : instruction budgetaire M14 (communes). M71 : regions avant la M57.
M57 = {**local.FONCTIONS_M57, "4": "Santé et action sociale",
       "01": "Opérations non ventilables", "02": "Administration générale", "03": "Conseils",
       "04": "Coopération décentralisée, action européenne et internationale", "05": "Gestion des fonds européens",
       "10": "Services communs", "11": "Police, sécurité, justice", "12": "Incendie et secours",
       "13": "Hygiène et salubrité publique", "18": "Autres interventions de protection des personnes et des biens",
       "20": "Services communs", "21": "Enseignement du premier degré", "22": "Enseignement du second degré",
       "23": "Enseignement supérieur", "24": "Cités scolaires", "25": "Formation professionnelle",
       "26": "Apprentissage", "27": "Formation sanitaire et sociale",
       "28": "Autres services périscolaires et annexes", "29": "Sécurité",
       "30": "Services communs", "31": "Culture", "32": "Sports", "33": "Jeunesse (action socio-éducative…) et loisirs",
       "34": "Vie sociale et citoyenne", "40": "Services communs", "41": "Santé", "42": "Action sociale",
       "43": "APA", "44": "RSA - Régularisations de RMI", "48": "Autres actions", "50": "Services communs",
       "51": "Aménagement et services urbains", "52": "Politique de la ville",
       "53": "Agglomérations et villes moyennes", "54": "Espace rural et autres espaces de développement",
       "55": "Habitat (Logement)", "56": "Actions en faveur du littoral",
       "57": "Technologies de l'information et de la communication", "58": "Autres actions", "59": "Sécurité",
       "60": "Services communs", "61": "Interventions économiques transversales",
       "62": "Structure d'animation et de développement économique", "63": "Actions sectorielles",
       "64": "Rayonnement et attractivité du territoire", "65": "Insertion économique et économie sociale et solidaire",
       "66": "Maintien et développement des services publics", "67": "Recherche et innovation", "68": "Autres actions",
       "70": "Services communs", "71": "Aménagement et développement urbain",
       "72": "Actions en matière de déchets et de propreté urbaine", "73": "Actions en matière de gestion des eaux",
       "74": "Politique de l'air", "75": "Politique de l'énergie",
       "76": "Préservation du patrimoine naturel et gestion des risques technologiques",
       "77": "Environnement des infrastructures de transports", "78": "Autres actions", "80": "Services communs",
       "81": "Transports scolaires", "82": "Transports publics de voyageurs", "83": "Transports de marchandises",
       "84": "Voirie", "85": "Infrastructures", "86": "Liaisons multimodales", "87": "Circulations douces",
       "88": "Autres", "89": "Sécurité"}
M14 = {"0": "Services généraux des administrations publiques locales", "1": "Sécurité et salubrité publiques",
       "2": "Enseignement, formation", "3": "Culture", "4": "Sport et jeunesse", "5": "Interventions sociales et santé",
       "6": "Famille", "7": "Logement", "8": "Aménagement et services urbains, environnement", "9": "Action économique",
       "01": "Opérations non ventilables", "02": "Administration générale",
       "04": "Coopération décentralisée, actions européennes et internationales",
       "11": "Police, sécurité, justice", "12": "Hygiène et salubrité publique", "13": "Pompiers, incendies et secours",
       "20": "Services communs", "21": "Enseignement du premier degré", "22": "Enseignement du second degré",
       "23": "Enseignement supérieur", "24": "Formation continue", "25": "Hébergement et restauration scolaires",
       "30": "Services communs", "31": "Expression artistique", "32": "Conservation et diffusion des patrimoines",
       "33": "Action culturelle", "40": "Services communs", "41": "Sport", "42": "Jeunesse",
       "50": "Services communs", "51": "Santé", "52": "Interventions sociales", "60": "Services communs",
       "61": "Services en faveur des personnes âgées", "63": "Aides à la famille", "64": "Crèches et garderies",
       "70": "Services communs", "71": "Parc privé de la ville", "72": "Aide au secteur locatif",
       "73": "Aide à l'accession à la propriété", "80": "Services communs", "81": "Services urbains",
       "82": "Aménagement urbain", "83": "Environnement", "90": "Interventions économiques",
       "91": "Foires et marchés", "92": "Aides à l'agriculture et aux industries agro-alimentaires",
       "93": "Aides à l'énergie, aux industries manufacturières et au BTP",
       "94": "Aides au commerce et aux services marchands", "95": "Aides au tourisme"}
M71 = {"0": "Services généraux", "1": "Formation professionnelle et apprentissage", "2": "Enseignement",
       "3": "Culture, sports et loisirs", "4": "Santé et action sociale", "5": "Aménagement des territoires",
       "6": "Gestion des fonds européens", "7": "Environnement", "8": "Transports", "9": "Action économique"}
NOMENCLATURES = {"M57": M57, "M57A": M57, "M14": M14, "M71": M71}

# Raccourcis vers les questions courantes : prefixes de codes de fonction, par nomenclature (communes et EPCI).
THEMES = {
    "ecoles": {"libelle": "Écoles (enseignement du premier degré)", "M57": ["21"], "M14": ["21"]},
    "periscolaire_restauration": {"libelle": "Périscolaire, hébergement et restauration scolaires",
                                  "M57": ["28"], "M14": ["25"]},
    "voirie": {"libelle": "Voirie", "M57": ["84"], "M14": ["821", "822"]},
    "culture": {"libelle": "Culture", "M57": ["31"], "M14": ["3"]},
    "sport": {"libelle": "Sport", "M57": ["32"], "M14": ["41"]},
    "jeunesse_loisirs": {"libelle": "Jeunesse et loisirs", "M57": ["33"], "M14": ["42"]},
    "action_sociale": {"libelle": "Action sociale", "M57": ["42"], "M14": ["52"]},
}
COLONNES = ["fonctionnement_eur", "investissement_eur", "fonctionnement_eur_hab", "investissement_eur_hab",
            "fonctionnement_sur_100", "investissement_sur_100"]
MASQUE = {"commune": 1, "epci": 2, "region": 4}


# --- Extraction -----------------------------------------------------------------------------------------------------


def extrait(annee: str, nom: str, rafraichir=False) -> Path:
    """Export CSV agrege cote serveur : siren x categorie x nomenclature x code de fonction (quelques Mo)."""
    filtre = FORMULES[nom][0]
    where = (f'cbudg="1" and categ in ({",".join(chr(34) + c + chr(34) for c in CATEGS)}) and {filtre}')
    params = {"select": "siren,categ,nomen,fonction,sum(obnetdeb) as d,sum(obnetcre) as c", "where": where,
              "group_by": "siren,categ,nomen,fonction", "delimiter": ";"}
    return local.en_cache(f"fonctions/{annee}_{nom}.csv", f"{ECO}/{DATASETS[annee]}/exports/csv", params, rafraichir)


def lire_extrait(p: Path) -> list[dict]:
    texte = p.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def code_fonction(code: str, nomen: str) -> str:
    """Code de fonction publie -> code de la nomenclature. Collectivites qui votent leur budget par fonction (M57,
    M71 : regions, Paris, quelques communes et EPCI) : la balance porte le chapitre devant la fonction, 90<f>
    (investissement ventile) et 93<f> (fonctionnement ventile) -> <f> ; chapitres 92x, 94x, 95x (operations non
    ventilees) -> 01. En M14, les codes 9x sont des fonctions (action economique) : laisses tels quels."""
    code = (code or "").strip()
    if len(code) >= 3 and (nomen.startswith("M57") or nomen == "M71"):
        if code[:2] in ("90", "93"):
            return code[2:]
        if code[:2] in ("92", "94", "95"):
            return "01"
    return code


def agreger(lignes_par_formule: dict[str, list[dict]]) -> dict:
    """{formule: lignes CSV} -> {siren: {"categ", "nomen", "codes": {code brut ou "": [F, I]}}} (euros, flottants)."""
    res: dict = {}
    for nom, lignes in lignes_par_formule.items():
        _, col, signe = FORMULES[nom]
        i = 0 if nom == "fonctionnement" else 1
        for r in lignes:
            d, c = local.num(r["d"]) or 0.0, local.num(r["c"]) or 0.0
            v = signe * (d - c if col == "d-c" else d if col == "d" else c)
            x = res.setdefault(r["siren"], {"categ": r["categ"], "nomen": r["nomen"], "codes": {}})
            if r["nomen"] and r["nomen"] < x["nomen"]:  # ordre explicite si un siren a deux nomenclatures
                x["nomen"] = r["nomen"]
            code = code_fonction(r["fonction"], r["nomen"] or "")
            x["codes"].setdefault(code, [0.0, 0.0])[i] += v
    return res


def ventiler(codes: dict, nomen: str, population, themes: bool) -> dict:
    """Codes bruts -> niveaux 1 et 2 (+ themes) : [F, I, F/hab, I/hab, F sur 100, I sur 100]."""
    tot = [sum(v[0] for v in codes.values()), sum(v[1] for v in codes.values())]
    nv = codes.get("", [0.0, 0.0])
    base = tot[0] + tot[1]

    def ligne(f, i):
        f, i = local.euros(f), local.euros(i)
        s = (lambda x: round(100 * x / base, 2) if base > 0 else None)
        return [f, i, local.par_hab(f, population), local.par_hab(i, population), s(f), s(i)]

    niv = defaultdict(lambda: [0.0, 0.0])
    for code, (f, i) in codes.items():
        if not code:
            continue
        for n in (1, 2):
            if len(code) >= n:
                niv[code[:n]][0] += f
                niv[code[:n]][1] += i
    out = {"nomenclature": nomen, "population": population,
           "total": ligne(*tot), "non_ventile": ligne(*nv),
           "part_ventilee": round(1 - (nv[0] + nv[1]) / base, 4) if base > 0 else None,
           "f": {k: ligne(*niv[k]) for k in sorted(niv)}}
    if themes:
        cle = "M57" if nomen.startswith("M57") else nomen
        th = {}
        for t, d in THEMES.items():
            if cle not in d:
                continue
            f = sum(v[0] for c, v in codes.items() if c and any(c.startswith(p) for p in d[cle]))
            i = sum(v[1] for c, v in codes.items() if c and any(c.startswith(p) for p in d[cle]))
            th[t] = ligne(f, i)
        out["themes"] = th
    return out


# --- Production -----------------------------------------------------------------------------------------------------


def charger(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def references() -> dict:
    """Communes, EPCI, regions : nom, rattachement et population OFGL par exercice (fichiers de pipeline/local.py)."""
    communes, epci, siren_insee = {}, {}, {}
    for p in sorted((local.OUT / "geo").glob("*.json")):
        g = charger(p)
        dep = g["departement"]["code"]
        pops = (charger(local.OUT / "budgets" / "communes" / f"{dep}.json") or {"collectivites": {}})["collectivites"]
        pop_e = (charger(local.OUT / "budgets" / "epci" / f"{dep}.json") or {"collectivites": {}})["collectivites"]
        for insee, c in g["communes"].items():
            communes[insee] = {**c, "pop": pops.get(insee, {}).get("population", {})}
            if c.get("siren"):
                siren_insee[c["siren"]] = insee
        for s, e in g["epci"].items():
            x = epci.setdefault(s, {"nom": e["nom"], "population": e.get("population"),
                                    "departement_siege": e["departement_siege"], "pop": {}})
            if s in pop_e:
                x["pop"] = pop_e[s].get("population", {})
    for p in sorted((local.OUT / "budgets" / "epci").glob("*.json")):  # population OFGL quel que soit le fichier
        for s, e in charger(p)["collectivites"].items():
            if s in epci and not epci[s]["pop"]:
                epci[s]["pop"] = e.get("population", {})
    regions = {}
    for code, r in (charger(local.OUT / "budgets" / "regions.json") or {"collectivites": {}})["collectivites"].items():
        if r.get("siren"):
            regions[r["siren"]] = {"code": code, "nom": r.get("nom"), "pop": r.get("population", {})}
    return {"communes": communes, "epci": epci, "regions": regions, "siren_insee": siren_insee}


def population(pop_ofgl: dict, annee: str, defaut):
    return pop_ofgl.get(annee) or defaut


def produire(rafraichir=False) -> dict:
    annees = sorted(DATASETS)
    ref = references()
    donnees = {a: agreger({n: lire_extrait(extrait(a, n, rafraichir)) for n in FORMULES}) for a in annees}
    stats = {"annees": annees, "hors_referentiel": defaultdict(int)}
    par_dep = defaultdict(lambda: {"communes": {}, "epci": {}})
    regions_out = {}
    for insee, c in sorted(ref["communes"].items()):
        dep = c["departement"]
        par_dep[dep]["communes"][insee] = {"nom": c["nom"], "siren": c.get("siren"), "annees": {}}
    for s, e in sorted(ref["epci"].items()):
        par_dep[e["departement_siege"]]["epci"][s] = {"nom": e["nom"], "siren": s, "annees": {}}
    for a in annees:
        for siren, x in sorted(donnees[a].items()):
            typ = CATEGS[x["categ"]]
            if typ == "commune":
                insee = ref["siren_insee"].get(siren)
                if not insee:
                    stats["hors_referentiel"][f"commune {a}"] += 1
                    continue
                c = ref["communes"][insee]
                obj = par_dep[c["departement"]]["communes"][insee]
                obj["annees"][a] = ventiler(x["codes"], x["nomen"], population(c["pop"], a, c.get("population")), True)
            elif typ == "epci":
                e = ref["epci"].get(siren)
                if not e:
                    stats["hors_referentiel"][f"epci {a}"] += 1
                    continue
                obj = par_dep[e["departement_siege"]]["epci"][siren]
                obj["annees"][a] = ventiler(x["codes"], x["nomen"], population(e["pop"], a, e.get("population")), True)
            else:
                r = ref["regions"].get(siren)
                if not r:
                    stats["hors_referentiel"][f"region {a}"] += 1
                    continue
                obj = regions_out.setdefault(r["code"], {"nom": r["nom"], "siren": siren, "annees": {}})
                obj["annees"][a] = ventiler(x["codes"], x["nomen"], population(r["pop"], a, None), False)
    entete = {"millesime": f"Comptes {annees[0]} a {annees[-1]} (exercices clos, balances DGFiP)",
              "source": SOURCE.format(annees=", ".join(annees)), "annees": annees, "colonnes": COLONNES,
              "unite": "euros ; eur_hab = euros / population OFGL de l'exercice ; sur_100 = part (en euros) de 100 "
                       "euros de depenses totales (fonctionnement + investissement) de la collectivite",
              "methode": METHODE}
    vider()
    octets = 0
    masques = {}
    cpt = defaultdict(lambda: defaultdict(int))
    pop_tot = sum(c.get("population") or 0 for c in ref["communes"].values())
    for dep in sorted(par_dep):
        d = par_dep[dep]
        for insee, c in d["communes"].items():
            c["statut"] = "publie" if c["annees"] else "non_publie"
            if not c["annees"]:
                del c["annees"]
            else:
                for a in annees:
                    c["annees"].setdefault(a, None)
        for s, e in list(d["epci"].items()):
            if not e["annees"]:
                del d["epci"][s]
            else:
                for a in annees:
                    e["annees"].setdefault(a, None)
        octets += local.dump(OUT / f"{dep}.json", {
            **entete, "departement": dep, "non_publie": NON_PUBLIE,
            "format": "communes.<insee>.annees.<annee>.f.<code> = valeurs alignees sur `colonnes` ; annee null = "
                      "presentation par fonction non publiee cet exercice ; statut non_publie = aucun exercice",
            "communes": d["communes"], "epci": d["epci"]})
    for code, r in regions_out.items():
        for a in annees:
            r["annees"].setdefault(a, None)
    octets += local.dump(OUT / "regions.json", {**entete, "regions": dict(sorted(regions_out.items()))})
    publie_epci = {s for d in par_dep.values() for s in d["epci"]}
    publie_reg = set(regions_out)
    for dep, d in sorted(par_dep.items()):
        for insee, c in d["communes"].items():
            r = ref["communes"][insee]
            m = (MASQUE["commune"] if c["statut"] == "publie" else 0) \
                | (MASQUE["epci"] if r.get("epci") in publie_epci else 0) \
                | (MASQUE["region"] if r.get("region") in publie_reg else 0)
            masques[insee] = m
            for a in annees:
                if c.get("annees", {}).get(a):
                    cpt[a]["communes"] += 1
                    cpt[a]["population"] += r.get("population") or 0
    couverture = {a: {"communes": cpt[a]["communes"], "communes_total": len(ref["communes"]),
                      "part_population": round(cpt[a]["population"] / pop_tot, 4) if pop_tot else None,
                      "epci": sum(1 for d in par_dep.values() for e in d["epci"].values() if e["annees"].get(a)),
                      "regions": sum(1 for r in regions_out.values() if r["annees"].get(a))} for a in annees}
    octets += local.dump(OUT / "index.json", {
        "millesime": f"Sources collectees au {date_sources()} ; comptes {annees[0]} a {annees[-1]}",
        "source": SOURCE.format(annees=", ".join(annees)), "annees": annees, "colonnes": COLONNES,
        "methode": METHODE, "non_publie": NON_PUBLIE,
        "fichiers": {"commune": "fonctions/<dep>.json (communes)", "epci": "fonctions/<departement_siege>.json (epci)",
                     "region": "fonctions/regions.json"},
        "nomenclatures": {k: dict(sorted(v.items())) for k, v in NOMENCLATURES.items() if k != "M57A"},
        "themes": THEMES, "masques": MASQUE,
        "format": "communes.<insee> = masque : 1 commune publiee (au moins un exercice), 2 EPCI publie, 4 region publiee",
        "couverture": couverture, "communes": masques})
    stats.update({"couverture": couverture, "taille_octets": octets,
                  "hors_referentiel": dict(stats["hors_referentiel"])})
    return stats


def vider() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rafraichir", action="store_true", help="retelecharger les extraits agreges")
    a = ap.parse_args(argv)
    print(json.dumps(produire(a.rafraichir), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
