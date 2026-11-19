"""Qui a voté tes impôts : chaque impôt que le simulateur montre, relié aux décisions publiques du Parlement qui l'ont
fixé ou modifié pendant la 17e législature (articles des lois de finances et de financement de la sécurité sociale,
amendements adoptés, scrutins publics avec le vote de chaque député).

Entrées (entrepôt local data/lake/, non versionné) :
  decisions/decisions_an_l17_amendements.zip, _scrutins.zip, _dossiers.zip     Assemblée nationale (mêmes fichiers que
  decisions/decisions_senat_ameli.zip                                            pipeline/decisions.py : aucune collecte
                                                                                 en double ; lecteurs repris de ce module)
  qui_a_vote/qui_a_vote_an_l17_acteurs.zip    députés de la législature, mandats et groupes (AMO30, historique) : nom,
                                             circonscription, groupe ; rien d'autre n'est lu
  qui_a_vote/textes/<uid>.html               textes examinés en séance (projets de loi, textes de nouvelle lecture ou
                                             de commission mixte paritaire), format ouvert de l'Assemblée nationale
Sorties (site/data/qui_a_vote/, chaque fichier < 1 Mo) :
  index.json                 impôts couverts, méthode de rattachement, avertissements, départements et circonscriptions
  impot_<id>.json            par impôt : articles rattachés (texte, lecture, intitulé officiel, preuve), scrutins publics
                             (décompte par groupe tel que publié), amendements adoptés nommés (Assemblée, Sénat)
  votes_<id>.json            par impôt : vote nominatif de chaque député à chaque scrutin retenu (chargé à la demande)
  scrutins.json              liste des scrutins retenus (tous impôts) pour l'entrée « Ton député »
  departements/<code>.json   par circonscription : députés de la législature (dates du mandat) et position à chaque
                             scrutin retenu (pour, contre, abstention, non-votant, délégation, mise au point)

Commandes :
  python pipeline/qui_a_vote.py collecter   # réseau : acteurs (AMO30) et textes examinés en séance, contrôle
                                            # d'intégrité (collecte/integrite.py) avant renommage, aucun contournement
  python pipeline/qui_a_vote.py produire    # sans réseau

Rattachement impôt <-> texte (règle 13 : jamais « par déduction ») : un article ou un amendement est relié à un impôt
seulement si (a) son dispositif cite un article de code qui fixe un paramètre que le simulateur applique pour cet impôt
(liste `IMPOTS[].bases`), ou (b) l'intitulé officiel de l'article (projet de loi déposé) nomme l'impôt, ou (c) pour un
amendement, il porte sur un article lui-même rattaché (« article visé »). Les alinéas de gage (« à due concurrence »)
sont ignorés. Un article dont le texte n'est pas retrouvé n'est pas rattaché.

Personnes : élus nommés comme auteurs d'amendements et par leur vote nominatif publié (décision du propriétaire du
19/11/2026, docs/NEUTRALITE.md). Seuls le nom, le groupe, la circonscription, le vote et l'amendement sont écrits. Un
élu qui a été candidat à une élection nationale est nommé comme les autres (décision du 19/11/2026, levée du masquage
de la règle 2.11) ; rien d'autre n'est écrit sur lui.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decisions as D  # noqa: E402  (lecteurs AN/Sénat, dump Ameli)

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
ENTREPOT = LAKE / "qui_a_vote"
TEXTES = ENTREPOT / "textes"
ACTEURS = ENTREPOT / "qui_a_vote_an_l17_acteurs.zip"   # entrée qui_a_vote_an_l17_acteurs du catalogue
SITE = ROOT / "site" / "data"
SORTIE = SITE / "qui_a_vote"

URL_ACTEURS = ("https://data.assemblee-nationale.fr/static/openData/repository/17/amo/tous_acteurs_mandats_organes_xi_"
               "legislature/AMO30_tous_acteurs_tous_mandats_tous_organes_historique.json.zip")
URL_TEXTE = "https://www.assemblee-nationale.fr/dyn/opendata/{uid}.html"
URL_SCRUTIN = "https://www.assemblee-nationale.fr/dyn/17/scrutins/{n}"
URL_AMDT = "https://www.assemblee-nationale.fr/dyn/17/amendements/{uid}"

SRC = ("Assemblée nationale (data.assemblee-nationale.fr, 17e législature : scrutins, amendements, dossiers, acteurs ; "
       "textes examinés en séance au format ouvert) ; Sénat (data.senat.fr, base Ameli) ; Licence Ouverte 2.0")
MILLESIME = "17e législature (depuis juillet 2024)"
SEANCE_AN = "PO838901"   # organe « Assemblée nationale » (séance publique)
LIMITE_OCTETS = 1_000_000

# --- Impôts du simulateur et bases légales de leurs paramètres ---------------------------------------------------------
# Liste reprise de web/src/calcul : familles impot_revenu et csg_crds (moteur, baremes-2025.ts), taxes sur la
# consommation (hors-bulletin.ts, LIBELLES_CONSO : tva, ticpe, tabac, alcool, autres = électricité, gaz, assurances),
# impôts locaux (taxe_fonciere, teom). Les cotisations sociales n'ont pas de base unique fixée par la loi (taux fixés
# par décret) : non couvertes, avec ce motif.
CODES = {
    "CGI": "code général des impôts",
    "CSS": "code de la sécurité sociale",
    "CIBS": "code des impositions sur les biens et services",
    "CRDS": "ordonnance n° 96-50 du 24 janvier 1996 relative au remboursement de la dette sociale",
}
SUFFIXES = ("bis|ter|quater|quinquies|sexies|septies|octies|nonies|novies|decies|undecies|duodecies|terdecies|"
            "quaterdecies|quindecies|sexdecies|septdecies|octodecies|novodecies|vicies|tricies")
LATIN = SUFFIXES.split("|")


def _plage(code: str, debut: int, fin: int):
    return lambda c, a: c == code and debut <= base(a) <= fin


def _exact(code: str, *ids: str):
    s = set(ids)
    return lambda c, a: c == code and a in s


def _prefixe(code: str, *prefixes: str):
    return lambda c, a: c == code and any(a == p.rstrip("-") or a.startswith(p) for p in prefixes)


IMPOTS = [
    {"id": "impot_revenu", "libelle": "Impôt sur le revenu",
     "lignes_simulateur": ["impôt sur le revenu du foyer (barème, quotient familial, décote)", "versement libératoire"],
     "bases_texte": ["articles 193 à 197 C du code général des impôts (barème, quotient familial, décote)",
                     "articles 204 A à 204 N (prélèvement à la source)", "article 83 (déduction de 10 %)",
                     "article 157 bis (abattement des plus de 65 ans)",
                     "article 81 bis (salaire des apprentis)", "articles 50-0, 102 ter et 151-0 (micro-entreprise, "
                     "versement libératoire)"],
     "bases": [_plage("CGI", 193, 197), _prefixe("CGI", "204 "), _exact("CGI", "83", "157 bis", "81 bis",
                                                                       "50-0", "102 ter", "151-0")],
     "intitule": r"imp[ôo]t sur le revenu"},
    {"id": "csg", "libelle": "Contribution sociale généralisée (CSG)",
     "lignes_simulateur": ["CSG sur les salaires, traitements, pensions et revenus d'activité"],
     "bases_texte": ["articles L. 136-1 à L. 136-5 et L. 136-8 du code de la sécurité sociale (revenus d'activité et "
                     "de remplacement, taux) ; les articles sur les revenus du patrimoine et des placements (L. 136-6, "
                     "L. 136-7) ne sont pas appliqués par le simulateur"],
     "bases": [lambda c, a: c == "CSS" and a.startswith("L. 136-") and _rang(a, 1) in (1, 2, 3, 4, 5, 8)],
     "intitule": r"contribution sociale g[ée]n[ée]ralis[ée]e"},
    {"id": "crds", "libelle": "Contribution pour le remboursement de la dette sociale (CRDS)",
     "lignes_simulateur": ["CRDS sur les revenus d'activité et de remplacement"],
     "bases_texte": ["articles 14 à 19 de l'ordonnance n° 96-50 du 24 janvier 1996"],
     "bases": [lambda c, a: c == "CRDS" and 14 <= base(a) <= 19],
     "intitule": r"remboursement de la dette sociale"},
    {"id": "tva", "libelle": "Taxe sur la valeur ajoutée (TVA)",
     "lignes_simulateur": ["TVA estimée sur ta consommation"],
     "bases_texte": ["articles 256 à 298 du code général des impôts (champ, taux, exonérations)"],
     "bases": [_plage("CGI", 256, 298)],
     "intitule": r"taxe sur la valeur ajout[ée]e"},
    {"id": "accises_energie", "libelle": "Accises sur les énergies (carburants, électricité, gaz)",
     "lignes_simulateur": ["taxe sur les carburants (accise, ex-TICPE)", "électricité et gaz (partie de « autres taxes "
                                                                          "sur les produits »)"],
     "bases_texte": ["articles L. 312-1 à L. 312-107 du code des impositions sur les biens et services"],
     "bases": [_prefixe("CIBS", "L. 312-")],
     "intitule": r"accises? sur (?:les |l['’])?(?:[ée]nergies?|[ée]lectricit[ée]|gaz|produits [ée]nerg[ée]tiques|"
                 r"carburants)|taxe int[ée]rieure de consommation sur les produits [ée]nerg[ée]tiques"},
    {"id": "tabac", "libelle": "Accise sur les tabacs",
     "lignes_simulateur": ["taxes sur le tabac"],
     "bases_texte": ["articles L. 314-1 à L. 314-35 du code des impositions sur les biens et services",
                     "articles 575 à 575 M du code général des impôts (rédaction antérieure)"],
     "bases": [_prefixe("CIBS", "L. 314-"), lambda c, a: c == "CGI" and base(a) == 575],
     "intitule": r"\btabacs?\b"},
    {"id": "alcool", "libelle": "Taxes sur les alcools",
     "lignes_simulateur": ["taxes sur les alcools"],
     "bases_texte": ["articles L. 313-1 à L. 313-37 du code des impositions sur les biens et services",
                     "articles L. 245-7 à L. 245-12 du code de la sécurité sociale (cotisation sur les boissons "
                     "alcooliques)"],
     "bases": [_prefixe("CIBS", "L. 313-"),
               lambda c, a: c == "CSS" and a.startswith("L. 245-") and 7 <= _rang(a, 1) <= 12],
     "intitule": r"\balcool|boissons alcooliques"},
    {"id": "taxe_fonciere", "libelle": "Taxe foncière sur les propriétés bâties",
     "lignes_simulateur": ["taxe foncière (montant de l'avis ou estimation)"],
     "bases_texte": ["articles 1380 à 1391 E du code général des impôts", "article 1518 bis (revalorisation des "
                                                                         "valeurs locatives)"],
     "bases": [_plage("CGI", 1380, 1391), _exact("CGI", "1518 bis")],
     "intitule": r"taxe fonci[èe]re"},
    {"id": "teom", "libelle": "Taxe d'enlèvement des ordures ménagères",
     "lignes_simulateur": ["taxe d'enlèvement des ordures ménagères (estimée)"],
     "bases_texte": ["articles 1520 à 1526 du code général des impôts"],
     "bases": [_plage("CGI", 1520, 1526)],
     "intitule": r"enl[èe]vement des ordures m[ée]nag[èe]res"},
]
NON_COUVERTS = [
    {"id": "cotisations", "libelle": "Cotisations sociales (salariales et patronales)",
     "motif": "taux fixés pour l'essentiel par décret, sans article de loi unique qui les porte : aucun rattachement "
              "sourcé possible à un article de loi de financement"},
]
LIBELLES_CONSO_SIMULATEUR = {"tva": "tva", "ticpe": "accises_energie", "autres": "accises_energie", "tabac": "tabac",
                             "alcool": "alcool"}

METHODE = (
    "Un article ou un amendement est relié à un impôt seulement si son texte cite un article de code qui fixe un "
    "paramètre appliqué par le simulateur pour cet impôt (liste « bases légales » de chaque impôt), si l'intitulé "
    "officiel de l'article, dans le projet de loi déposé, nomme l'impôt, ou, pour un amendement, s'il porte sur un "
    "article dont toutes les dispositions relèvent de cet impôt (article visé). Les alinéas de gage (« à due "
    "concurrence ») et le texte inséré entre guillemets ne comptent pas ; un article qui porte sur la destination du "
    "produit (affectation, fraction, compensation) n'est pas relié. Un article dont le texte n'a pas été retrouvé "
    "n'est pas relié : rien n'est attribué par déduction.")
AVERTISSEMENTS = [
    "Un vote sur un article n'est pas un vote sur l'impôt entier : l'article ne modifie qu'une partie des règles de "
    "l'impôt, et d'autres dispositions du même article peuvent porter sur autre chose.",
    "Un député non-votant n'est pas forcément absent : la présidente ou le président de séance et les membres du "
    "Gouvernement ne votent pas ; un député peut aussi être présent sans prendre part au vote.",
    "Un député peut voter pour un collègue qui lui a donné délégation (une délégation au plus) : le vote est alors "
    "publié au nom du député qui a délégué, avec la mention « par délégation ».",
    "Une mise au point est la déclaration publiée d'un député qui indique qu'il voulait voter autrement : elle est "
    "affichée à côté du vote, elle ne change pas le résultat du scrutin.",
    "Un député absent d'une liste nominative n'a pas de position enregistrée pour ce scrutin : la source ne dit pas "
    "pourquoi.",
    "Le Sénat ne publie pas ses scrutins nominatifs en données ouvertes : seuls les amendements adoptés au Sénat sont "
    "repris, avec leur auteur.",
]
REGLE_ORDRE_GROUPES = "Groupes politiques classés par ordre alphabétique de leur nom ; députés par ordre alphabétique."
REGLE_ORDRE_LISTES = ("Textes du plus récent au plus ancien ; dans un texte, articles et scrutins dans l'ordre du texte "
                      "et de leur numéro ; amendements par date de décision, quel que soit le groupe de l'auteur.")
REGLE_PERSONNES = ("Les parlementaires sont nommés comme auteurs d'amendements et par leur vote nominatif publié aux "
                   "scrutins publics : nom, groupe, circonscription, vote. Aucune autre donnée personnelle (ni date de "
                   "naissance, ni adresse, ni profession, ni patrimoine, ni photo).")
POSITIONS = {"pours": "pour", "contres": "contre", "abstentions": "abstention", "nonVotants": "non_votant",
             "nonVotantsVolontaires": "non_votant"}

# --- Citations d'articles de code -------------------------------------------------------------------------------------

NUM = (r"(?:L\.\s?|L\s|LO\s|R\.\s?)?\d+(?:-\d+)*(?:\s(?:[A-Z]{1,2}|" + SUFFIXES + r")(?![\w-]))*")
LISTE = NUM + r"(?:\s*(?:,|et|à|ou)\s*" + NUM + r")*"
CODE_RE = (r"(code g[ée]n[ée]ral des imp[ôo]ts|code de la s[ée]curit[ée] sociale|code des impositions sur les biens et "
           r"services|ordonnance n°\s?96-50)")
EXPLICITE = re.compile(r"\barticles?\s+(" + LISTE + r")\s+(?:du|de la|de l['’])\s+" + CODE_RE, re.I)
MEME_CODE = re.compile(r"\barticles?\s+(" + LISTE + r")\s+(?:du|de ce)\s+(?:même|présent|dit)\s+code|\barticles?\s+("
                       + LISTE + r")\s+du\s+code\s+(?:précité|susmentionné)", re.I)
NU = re.compile(r"\b(?:l['’]|les\s+|aux?\s+|des?\s+|de\s+l['’])?articles?\s+(" + LISTE + r")(?!\s*(?:du|de la|de l['’]|"
                r"de|des)\s+(?:loi|ordonnance|décret|règlement|directive|présente?|code|traité|livre))", re.I)
CONTEXTE = re.compile(CODE_RE + r"[^.;:«]*?\b(?:est|sont) ainsi (?:modifi|compl[ée]t|r[ée]dig)", re.I)
SECTION = re.compile(r"^[IVX]+\.\s*[-–—]\s*")
GAGE = re.compile(r"due concurrence|perte de recettes|charge (?:pour|résultant)|compens[ée]+s?\s+(?:à|par)", re.I)


def code_de(libelle: str) -> str:
    x = libelle.lower()
    if "impôts" in x or "impots" in x:
        return "CGI"
    if "sécurité" in x or "securite" in x:
        return "CSS"
    if "impositions" in x:
        return "CIBS"
    return "CRDS"


def norm_article(a: str) -> str:
    """« L.136‑8 », « 278‑0 bis », « 1391 B ter » -> « L. 136-8 », « 278-0 bis », « 1391 B ter »."""
    a = re.sub(r"[‐-–‑]", "-", a)
    a = re.sub(r"\s+", " ", a.replace(" ", " ")).strip()
    a = re.sub(r"^(L|R|LO)\.?\s?", lambda m: f"{m.group(1)}. ", a) if re.match(r"^(?:L|R|LO)[.\s]", a) else a
    return a.replace("LO. ", "LO ")


def base(a: str) -> int:
    m = re.search(r"(\d+)", a)
    return int(m.group(1)) if m else -1


def _rang(a: str, i: int) -> int:
    n = re.findall(r"\d+", a)
    return int(n[i]) if len(n) > i else -1


def _articles(liste: str) -> list[str]:
    out = []
    for m in re.finditer(NUM, liste):
        out.append(norm_article(m.group(0)))
    return out


def texte_brut(fragment_html: str) -> list[str]:
    """HTML -> alinéas (une ligne par paragraphe), entités décodées, espaces et tirets insécables normalisés."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment_html or "")
    s = re.sub(r"(?i)<br\s*/?>", " ", s)
    s = re.sub(r"(?i)</(p|li|h\d|div|tr|td|table)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("‑", "-").replace("‐", "-").replace(" ", " ").replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return [l.strip() for l in s.split("\n") if l.strip()]


def citations(alineas: list[str]) -> list[tuple[str, str]]:
    """Articles de code cités par un dispositif : [(code, article)] dans l'ordre, sans doublon.

    Citation explicite (« l'article 197 du code général des impôts »), ou article nu dans un bloc ouvert par « Le code
    X est ainsi modifié » (le bloc se ferme à la section suivante : « II. – »). Les alinéas de gage sont ignorés."""
    out: dict[tuple[str, str], None] = {}
    ctx = None
    for l in alineas:
        l = re.sub(r"[\u2010\u2011]", "-", l).replace("\u00a0", " ").replace("\u202f", " ")
        if SECTION.match(l):
            ctx = None
        if GAGE.search(l) or l.startswith(("«", "\"")):
            continue  # gage, ou texte inséré entre guillemets (ses renvois ne modifient pas les articles cités)
        l = re.sub(r"«[^»]*»", " ", l)
        dernier = ctx
        pris = []
        for m in EXPLICITE.finditer(l):
            c = code_de(m.group(2))
            for a in _articles(m.group(1)):
                out[(c, a)] = None
            pris.append(m.span())
            dernier = c
        for m in MEME_CODE.finditer(l):
            if dernier:
                for a in _articles(m.group(1) or m.group(2)):
                    out[(dernier, a)] = None
            pris.append(m.span())
        m = CONTEXTE.search(l)
        if m:
            ctx = code_de(m.group(1))
        elif ctx:
            for m in NU.finditer(l):
                if any(s <= m.start() < e for s, e in pris):
                    continue
                for a in _articles(m.group(1)):
                    out[(ctx, a)] = None
    return list(out)


def impots_cites(cits: list[tuple[str, str]]) -> dict[str, list[str]]:
    """{impôt: [preuves]} : articles de code cités qui fixent un paramètre appliqué par le simulateur."""
    out: dict[str, list[str]] = {}
    for c, a in cits:
        for imp in IMPOTS:
            if any(f(c, a) for f in imp["bases"]):
                out.setdefault(imp["id"], []).append(f"article {a} du {CODES[c]}" if c != "CRDS" else
                                                     f"article {a} de l'{CODES[c]}")
    return out


EXCLUS_INTITULE = re.compile(r"fonds de compensation|fractions?\b|affect[ée]e?s?\b|affectation|r[ée]partition|"
                             r"compensation|dotation", re.I)


def impots_intitule(intitule: str | None) -> list[str]:
    """Impôts nommés par l'intitulé officiel ; un intitulé qui porte sur la destination du produit (affectation,
    fraction versée, compensation, dotation) ne modifie pas les règles de l'impôt : non retenu."""
    if not intitule or EXCLUS_INTITULE.search(intitule):
        return []
    return [imp["id"] for imp in IMPOTS if re.search(imp["intitule"], intitule, re.I)]


def rattacher(intitule: str | None, alineas: list[str], intitule_projet: str | None = None) -> dict[str, dict]:
    """{impôt: {methode, preuves, article_entier}} pour un article d'un texte examiné.

    `intitule` : intitulé officiel porté par ce texte (projet déposé) ; `intitule_projet` : intitulé du même article
    dans le projet déposé, quand ce texte (nouvelle lecture) n'en porte pas : il sert seulement à écarter un article
    qui porte sur la destination du produit (affectation, fraction, compensation), jamais à relier.
    `article_entier` : toutes les dispositions de code citées relèvent de cet impôt (ou l'intitulé ne nomme que lui) ;
    seul un tel article transmet son rattachement aux amendements qui le visent."""
    if any(x and EXCLUS_INTITULE.search(x) for x in (intitule, intitule_projet)):
        return {}
    cits = citations(alineas)
    nommes = impots_intitule(intitule)
    out = {}
    for i in nommes:
        out[i] = {"methode": "intitule", "preuves": [f"intitulé officiel : « {intitule} »"]}
    for i, p in impots_cites(cits).items():
        if i in out:
            out[i]["preuves"] += p
            out[i]["methode"] = "intitule_et_code_cite"
        else:
            out[i] = {"methode": "code_cite", "preuves": p}
    for i, r in out.items():
        bases_i = next(x["bases"] for x in IMPOTS if x["id"] == i)
        r["article_entier"] = (nommes == [i]) or (bool(cits) and all(any(f(c, a) for f in bases_i) for c, a in cits))
    return out


# --- Textes examinés en séance (format ouvert de l'Assemblée) ---------------------------------------------------------

TETE = re.compile(r"^(?:ARTICLE|Article)\s+(premier|1er|liminaire|\d+)((?:\s+(?:" + SUFFIXES + r"|[A-Z]))*)"
                  r"(?:\s*\((?:nouveau|supprimé|Supprimé|pour coordination)\))?\s*(?::\s*(.+))?$")


def etiquette(num: str, suffixe: str = "") -> str:
    n = "1" if num.lower() in ("premier", "1er") else num.lower()
    return (n + " " + " ".join(suffixe.lower().split())).strip()


def articles_du_texte(page_html: str) -> dict[str, dict]:
    """{étiquette: {intitule, alineas}} : pour chaque article, l'intitulé officiel quand le texte en porte un (table des
    matières des projets déposés) et le dispositif le plus long trouvé sous son titre (exposé des motifs exclu)."""
    lignes = texte_brut(page_html)
    tetes = []
    for i, l in enumerate(lignes):
        m = TETE.match(l)
        if m and len(l) < 400:
            tetes.append((i, etiquette(m.group(1), m.group(2) or ""), (m.group(3) or "").strip() or None))
    out: dict[str, dict] = {}
    for k, (i, et, intit) in enumerate(tetes):
        fin = tetes[k + 1][0] if k + 1 < len(tetes) else len(lignes)
        corps = []
        for l in lignes[i + 1:fin]:
            if re.match(r"^(Exposé des motifs|EXPOSÉ DES MOTIFS|Évaluation préalable|ÉVALUATIONS? PRÉALABLES?)\b", l):
                break
            if re.fullmatch(r"\(\d+\)", l):
                continue
            corps.append(l)
        e = out.setdefault(et, {"intitule": None, "alineas": []})
        if intit and not e["intitule"]:
            e["intitule"] = intit
        if sum(map(len, corps)) > sum(map(len, e["alineas"])):
            e["alineas"] = corps
    return out


# --- Lecture des sources de l'Assemblée -------------------------------------------------------------------------------

TITRE_TEXTE = re.compile(r"^Projet de loi de (finances|financement de la s[ée]curit[ée] sociale)(?: (de fin de gestion|"
                         r"rectificative))? pour (\d{4})$", re.I)


def cle_texte(nature: str, variante: str | None, annee: str | int) -> str:
    if nature.lower().startswith("financement"):
        return f"PLFSS {annee}" if not variante else f"PLFRSS {annee}"
    if variante:
        return f"{'PLFG' if 'fin' in variante.lower() else 'PLFR'} {annee}"
    return f"PLF {annee}"


LIBELLE_TEXTE = {"PLF": "projet de loi de finances pour {a}", "PLFSS": "projet de loi de financement de la sécurité "
                 "sociale pour {a}", "PLFG": "projet de loi de finances de fin de gestion pour {a}",
                 "PLFR": "projet de loi de finances rectificative pour {a}",
                 "PLFRSS": "projet de loi de financement rectificative de la sécurité sociale pour {a}"}


def libelle_texte(cle: str) -> str:
    t, a = cle.split()
    return LIBELLE_TEXTE[t].format(a=a)


def dossiers() -> dict[str, str]:
    """{uid du dossier: clé du texte (« PLF 2026 », « PLFSS 2026 »…)} pour les lois financières de la législature."""
    out = {}
    with zipfile.ZipFile(D.AN_DOSSIERS) as z:
        for n in sorted(z.namelist()):
            if "dossierParlementaire" not in n:
                continue
            d = json.loads(z.read(n))["dossierParlementaire"]
            m = TITRE_TEXTE.match(D.propre(d["titreDossier"]["titre"]))
            if m:
                out[d["uid"]] = cle_texte(m.group(1), m.group(2), m.group(3))
    return out


def ordre_document(uid: str) -> tuple[int, int]:
    m = re.search(r"B(TC)?(\d+)$", uid)
    return (1 if m and m.group(1) else 0, int(m.group(2)) if m else 0)


def lecture_de(docs: list[str], uid: str) -> str:
    """Lecture d'un texte examiné en séance : premier projet = première lecture, suivant = nouvelle lecture, texte de
    commission mixte paritaire (« TC ») ; ordre des numéros de dépôt."""
    if ordre_document(uid)[0]:
        return "texte de la commission mixte paritaire"
    simples = [d for d in docs if not ordre_document(d)[0]]
    i = simples.index(uid)
    return ["première lecture", "nouvelle lecture", "lecture définitive"][min(i, 2)]


def amendements_an(dos: dict[str, str], noms: dict, groupes: dict) -> tuple[list[dict], dict[str, list[str]]]:
    """Amendements de séance publique des lois financières : numéro, texte, article visé, sort, auteur (élu nommé),
    dispositif. Renvoie aussi {clé du texte: [documents examinés en séance, ordre de dépôt]}."""
    out, docs = [], defaultdict(set)
    with zipfile.ZipFile(D.AN_AMDTS) as z:
        for n in sorted(z.namelist()):
            p = n.split("/")
            if len(p) < 4 or p[1] not in dos or SEANCE_AN not in p[3]:
                continue
            a = json.loads(z.read(n))["amendement"]
            if a["identification"].get("prefixeOrganeExamen") != "AN":
                continue
            cle, doc = dos[p[1]], a["texteLegislatifRef"]
            docs[cle].add(doc)
            div = (a.get("pointeurFragmentTexte") or {}).get("division") or {}
            vise = None
            if not D.nil(div) and propre_div(div.get("avant_A_Apres")) == "A" and div.get("type") == "ARTICLE":
                m = re.match(r"^ARTICLE\s+(PREMIER|1ER|\d+)((?:\s+[A-Z]+)*)", D.propre(div.get("articleDesignation"))
                             .upper())
                if m:
                    vise = etiquette(m.group(1), " ".join(w for w in (m.group(2) or "").split()
                                                          if w.lower() in LATIN or len(w) <= 2))
            corps = (a.get("corps") or {}).get("contenuAuteur") or {}
            disp = corps.get("dispositif")
            disp = "" if D.nil(disp) or not isinstance(disp, str) else disp
            sig = a["signataires"]
            aut = sig["auteur"]
            typ = D.propre(aut.get("typeAuteur"))
            if typ == "Gouvernement":
                auteur = {"type": "gouvernement", "nom": "Gouvernement", "groupe": None, "id": None}
            else:
                ref = aut.get("acteurRef") if isinstance(aut.get("acteurRef"), str) else None
                auteur = {"type": "député" if typ == "Député" else (typ.lower() or "autre"),
                          "nom": noms.get(ref), "groupe": groupes.get(_chaine(aut.get("groupePolitiqueRef"))), "id": ref}
            cv = a["cycleDeVie"]
            out.append({
                "uid": a["uid"], "texte": cle, "document": doc,
                "numero": re.sub(r"^[IVX]+-", "", D.propre(a["identification"].get("numeroLong"))),
                "numero_long": D.propre(a["identification"].get("numeroLong")),
                "article_vise": vise, "sort": D.sort_an(a),
                "date": (cv.get("dateSort") or "")[:10] if isinstance(cv.get("dateSort"), str) else None,
                "date_depot": cv.get("dateDepot") if isinstance(cv.get("dateDepot"), str) else None,
                "auteur": auteur, "cosignataires": len(D.listify((sig.get("cosignataires") or {}).get("acteurRef"))),
                "dispositif": disp})
    return out, {k: sorted(v, key=ordre_document) for k, v in docs.items()}


def _chaine(v) -> str | None:
    return v if isinstance(v, str) and v else None


def propre_div(v) -> str:
    return D.propre(v) if isinstance(v, str) else ""


def acteurs() -> tuple[dict, dict, dict, dict]:
    """Depuis l'historique des acteurs (AMO30) : noms ({PA: « Prénom Nom »}), groupes ({PO: libellé}), mandats de
    député de la 17e législature ({PM: {acteur, departement, num_departement, circonscription, debut, fin}}) et
    départements ({numéro: nom}). Rien d'autre n'est lu (ni état civil hors nom, ni adresse, ni profession)."""
    noms, groupes, mandats, deps = {}, {}, {}, {}
    with zipfile.ZipFile(ACTEURS) as z:
        for n in sorted(z.namelist()):
            if "/organe/" in n:
                o = json.loads(z.read(n))["organe"]
                if o.get("codeType") == "GP":
                    groupes[o["uid"]] = D.propre(o.get("libelle"))
                continue
            if "/acteur/" not in n:
                continue
            a = json.loads(z.read(n))["acteur"]
            uid = a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]
            i = a["etatCivil"]["ident"]
            noms[uid] = D.propre(f"{i.get('prenom') or ''} {i.get('nom') or ''}")
            for m in D.listify((a.get("mandats") or {}).get("mandat")):
                if m.get("typeOrgane") != "ASSEMBLEE" or str(m.get("legislature")) != "17":
                    continue
                lieu = ((m.get("election") or {}).get("lieu") or {})
                if not lieu.get("numDepartement"):
                    continue
                mandats[m["uid"]] = {"acteur": uid, "num_departement": D.propre(lieu["numDepartement"]),
                                     "circonscription": int(lieu.get("numCirco") or 0),
                                     # début d'exercice : prise de fonction (reprise après le Gouvernement,
                                     # suppléance), à défaut début du mandat
                                     "debut": (((m.get("mandature") or {}).get("datePriseFonction")
                                                if isinstance(m.get("mandature"), dict) else None)
                                               or m.get("dateDebut") or "")[:10] or None,
                                     "fin": (m.get("dateFin") or "")[:10] or None}
                deps[D.propre(lieu["numDepartement"])] = D.propre(lieu.get("departement"))
    return noms, groupes, mandats, deps


TITRE_SCRUTIN = re.compile(r"projet de loi (de finances|de financement de la s[ée]curit[ée] sociale)( de fin de gestion|"
                           r" rectificative)? pour (\d{4})", re.I)


def lecture_scrutin(titre: str) -> str | None:
    m = re.search(r"\(([^()]*(?:lecture|commission mixte paritaire)[^()]*)\)\.?\s*$", titre)
    if not m:
        return None
    x = m.group(1).lower()
    for k in ("première lecture", "nouvelle lecture", "lecture définitive"):
        if k in x:
            return k
    return "texte de la commission mixte paritaire" if "mixte" in x else None


def votants(bloc) -> list[tuple[str, str | None, bool]]:
    """[(acteur, mandat, par délégation)] d'une liste nominative de la source."""
    if D.nil(bloc) or not bloc:
        return []
    out = []
    for v in D.listify(bloc.get("votant") if isinstance(bloc, dict) else None):
        if isinstance(v, dict) and v.get("acteurRef"):
            out.append((v["acteurRef"], v.get("mandatRef"), str(v.get("parDelegation")).lower() == "true"))
    return out


def scrutins_an() -> list[dict]:
    """Scrutins publics sur les lois financières : objet, lecture, article ou amendement visé, décomptes publiés,
    listes nominatives par groupe, mises au point."""
    out = []
    with zipfile.ZipFile(D.AN_SCRUTINS) as z:
        for n in sorted(z.namelist()):
            s = json.loads(z.read(n))["scrutin"]
            titre = D.propre((s.get("objet") or {}).get("libelle") or s.get("titre"))
            m = TITRE_SCRUTIN.search(titre)
            if not m:
                continue
            cle = cle_texte(m.group(1), (m.group(2) or "").strip() or None, m.group(3))
            debut = titre[:m.start()]
            article = amdt = None
            ma = re.search(r"(?:sous-)?amen[a-z]*ment n[°o]\s*([A-Z]*-?\d+)", debut, re.I)
            if ma:
                amdt = re.sub(r"^[IVX]+-", "", ma.group(1))
            else:
                mt = re.match(r"^l['’]article\s+(premier|liminaire|\d+)((?:\s+(?:" + SUFFIXES + r"))*)\b", debut, re.I)
                if mt:
                    article = etiquette(mt.group(1), mt.group(2) or "")
            if not (article or amdt):
                continue
            synth = s["syntheseVote"]
            dec = synth["decompte"]
            groupes = []
            for g in D.listify(((s.get("ventilationVotes") or {}).get("organe") or {}).get("groupes", {}).get("groupe")):
                v = g.get("vote") or {}
                dv = v.get("decompteVoix") or {}
                dn = v.get("decompteNominatif") or {}
                pos = {}
                for cle_src, p in POSITIONS.items():
                    for acteur, mandat, deleg in votants(dn.get(cle_src)):
                        pos[acteur] = (p, mandat, deleg)
                groupes.append({"organe": g["organeRef"], "membres": int(g.get("nombreMembresGroupe") or 0),
                                "decompte": {"pour": int(dv.get("pour") or 0), "contre": int(dv.get("contre") or 0),
                                             "abstentions": int(dv.get("abstentions") or 0),
                                             "non_votants": int(dv.get("nonVotants") or 0)
                                             + int(dv.get("nonVotantsVolontaires") or 0)},
                                "positions": pos})
            mises = {}
            mp = s.get("miseAuPoint") or {}
            if isinstance(mp, dict):
                for cle_src, p in POSITIONS.items():
                    for acteur, _, _ in votants(mp.get(cle_src)):
                        mises[acteur] = p
            out.append({"numero": int(s["numero"]), "date": s["dateScrutin"], "texte": cle,
                        "lecture": lecture_scrutin(titre), "objet": titre.rstrip("."), "article": article,
                        "amendement_numero": amdt, "resultat": D.propre(s["sort"]["code"]),
                        "decompte": {"votants": int(synth.get("nombreVotants") or 0),
                                     "exprimes": int(synth.get("suffragesExprimes") or 0),
                                     "pour": int(dec.get("pour") or 0), "contre": int(dec.get("contre") or 0),
                                     "abstentions": int(dec.get("abstentions") or 0),
                                     "non_votants": int(dec.get("nonVotants") or 0)
                                     + int(dec.get("nonVotantsVolontaires") or 0)},
                        "nominatif": s.get("modePublicationDesVotes") == "DecompteNominatif",
                        "groupes": groupes, "mises_au_point": mises,
                        "url": URL_SCRUTIN.format(n=s["numero"])})
    return sorted(out, key=lambda x: x["numero"])


# --- Sénat (Ameli) ----------------------------------------------------------------------------------------------------


def amendements_senat() -> list[dict]:
    """Amendements adoptés en séance au Sénat sur les lois financières de la période (PLF 2025 et suivants, fin de
    gestion 2024 et suivantes, PLFSS 2025 et suivants). Auteur : premier signataire (nom, groupe)."""
    with zipfile.ZipFile(D.SENAT_AMELI) as z:
        nom = next(n for n in z.namelist() if n.endswith(".sql"))
        with z.open(nom) as fb:
            data = D.lire_copy(io.TextIOWrapper(fb, encoding="latin-1"),
                               {"txt_ameli", "ses", "sor", "amd", "amdsen", "grppol_ameli", "gvt", "com_ameli", "ent"},
                               filtre=lambda t, l: t != "amd" or "code" in l)
    ses = {s["id"]: s for s in data["ses"]}
    sor = {s["id"]: s for s in data["sor"]}
    grp = {g["entid"]: D.propre(g["libcou"]) for g in data["grppol_ameli"]}
    gvt = {g["entid"] for g in data["gvt"]} | {e["id"] for e in data["ent"] if e.get("typ") == "B"}
    com = {c["entid"]: D.propre(c["lib"]) for c in data["com_ameli"]}
    textes = {}
    for t in data["txt_ameli"]:
        m = re.search(r"^Projet de loi de (finances|financement de la s[ée]curit[ée] sociale)(?: (de fin de gestion|"
                      r"rectificative))? pour (\d{4})$", D.propre(t.get("int")), re.I)
        if not m:
            continue
        an = int(m.group(3))
        if an < 2025 and not (m.group(2) and an == 2024):
            continue
        textes[t["id"]] = {"texte": cle_texte(m.group(1), m.group(2), m.group(3)), "num": t.get("num"),
                           "session": (ses.get(t.get("sesinsid")) or {}).get("lil"),
                           "date": (t.get("datado") or t.get("datdep") or "")[:10] or None}
    auteurs = defaultdict(list)
    for r in data["amdsen"]:
        auteurs[r["amdid"]].append(r)
    out = []
    for a in data["amd"]:
        tx = textes.get(a["txtid"])
        so = sor.get(a.get("sorid")) or {}
        if not tx or not a.get("dis") or so.get("typ") != "S" or not D.propre(so.get("lib")).startswith("Adopté"):
            continue
        aus = sorted(auteurs.get(a["id"], []), key=lambda r: int(r.get("rng") or 99))
        if aus:
            r = aus[0]
            auteur = {"type": "sénateur", "nom": D.propre(f"{r.get('prenomuse') or ''} {r.get('nomuse') or ''}"),
                      "groupe": grp.get(r.get("grpid")), "id": None}
        elif a.get("nomentid") in gvt:
            auteur = {"type": "gouvernement", "nom": "Gouvernement", "groupe": None, "id": None}
        elif a.get("nomentid") in com:
            auteur = {"type": "commission", "nom": com[a["nomentid"]], "groupe": None, "id": None}
        else:
            auteur = {"type": "autre", "nom": None, "groupe": None, "id": None}
        url = (f"https://www.senat.fr/amendements/{tx['session']}/{tx['num']}/Amdt_{a['num']}.html"
               if tx["session"] and tx["num"] else None)
        out.append({"uid": f"SENAT-{a['id']}", "chambre": "Sénat", "texte": tx["texte"], "document": None,
                    "numero": D.propre(a.get("num")), "numero_long": D.propre(a.get("num")), "article_vise": None,
                    "sort": "Adopté", "date": (a.get("datdep") or "")[:10] or None, "auteur": auteur,
                    "cosignataires": max(len(aus) - 1, 0), "dispositif": a["dis"], "url": url,
                    "texte_ref": f"Sénat, texte n° {tx['num']} ({tx['session']})"})
    return out


# --- Production -------------------------------------------------------------------------------------------------------


def extrait(alineas: list[str], n: int = 600) -> str:
    t = " ".join(alineas)
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " […]"


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode("utf-8")) > LIMITE_OCTETS:
        raise SystemExit(f"{path} dépasse 1 Mo ({len(texte.encode('utf-8'))} octets) : découper")
    path.write_text(texte + "\n", encoding="utf-8")


def cle_tri_texte(cle: str) -> tuple:
    t, a = cle.split()
    return (-int(a), ["PLF", "PLFSS", "PLFG", "PLFR", "PLFRSS"].index(t))


def tri_article(et: str) -> tuple:
    p = et.split()
    n = int(p[0]) if p[0].isdigit() else 0
    return (n, LATIN.index(p[1]) + 1 if len(p) > 1 and p[1] in LATIN else 0, et)


def nom_fr(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def produire(sortie: Path = SORTIE) -> dict:
    for f in (D.AN_AMDTS, D.AN_SCRUTINS, D.AN_DOSSIERS, D.SENAT_AMELI, ACTEURS):
        if not f.exists():
            raise SystemExit(f"sources absentes de data/lake : {f.relative_to(ROOT)} (absente : lancer collecter, "
                             "python pipeline/qui_a_vote.py collecter ; zips de l'étape decisions)")
    t0 = time.time()
    noms, groupes, mandats, deps = acteurs()

    def nom_publie(pa: str | None) -> str | None:
        return None if pa is None else noms.get(pa)

    dos = dossiers()
    amdts, docs = amendements_an(dos, noms, groupes)
    print(f"  {len(amdts)} amendements de séance lus ({time.time() - t0:.0f} s)", flush=True)
    scr = scrutins_an()
    print(f"  {len(scr)} scrutins sur des articles ou amendements des lois financières", flush=True)

    # 1. articles des textes examinés en séance, rattachés aux impôts
    textes = {}
    manquants = []
    for cle, uids in sorted(docs.items()):
        for uid in uids:
            f = TEXTES / f"{uid}.html"
            if not f.exists():
                manquants.append(uid)
                continue
            textes[uid] = {"cle": cle, "lecture": lecture_de(uids, uid),
                           "articles": articles_du_texte(f.read_text(encoding="utf-8"))}
    # L'intitulé officiel n'est porté que par le projet déposé (premier texte du dossier). Les articles gardent leur
    # numéro d'une lecture à l'autre : en nouvelle lecture, l'intitulé du projet est affiché (« projet déposé ») et
    # sert à écarter un article d'affectation, jamais à relier (le dispositif a pu changer : seul le code cité relie).
    rattach_articles: dict[tuple[str, str], dict] = {}
    for uid, t in textes.items():
        projet = textes.get(docs[t["cle"]][0], {}).get("articles", {}) if docs[t["cle"]][0] != uid else {}
        for et, a in t["articles"].items():
            ip = (projet.get(et) or {}).get("intitule") if not a["intitule"] else None
            a["intitule_projet"] = ip
            r = rattacher(a["intitule"], a["alineas"], ip)
            if r:
                rattach_articles[(uid, et)] = r

    # 2. amendements de séance : rattachement par code cité ou par article visé
    for a in amdts:
        r = {i: {"methode": "code_cite", "preuves": p} for i, p in
             impots_cites(citations(texte_brut(a["dispositif"]))).items()}
        if a["article_vise"] and (a["document"], a["article_vise"]) in rattach_articles:
            for i, ra in rattach_articles[(a["document"], a["article_vise"])].items():
                if i not in r and ra["article_entier"]:
                    r[i] = {"methode": "article_vise",
                            "preuves": [f"amendement à l'article {a['article_vise']}, dont toutes les dispositions "
                                        "relèvent de cet impôt"]}
        a["rattachement"] = r
    index_amdt = defaultdict(list)
    for a in amdts:
        index_amdt[(a["texte"], a["numero"])].append(a)

    # 3. scrutins retenus : sur un article rattaché ou un amendement rattaché
    retenus = []
    for s in scr:
        uid_docs = docs.get(s["texte"], [])
        cible = None
        if s["article"] is not None:
            uid = next((u for u in uid_docs if s["lecture"] and lecture_de(uid_docs, u) == s["lecture"]), None)
            if uid and (uid, s["article"]) in rattach_articles:
                s["document"] = uid
                cible = rattach_articles[(uid, s["article"])]
        else:
            cands = index_amdt.get((s["texte"], s["amendement_numero"]), [])
            memes = [a for a in cands if a["date"] == s["date"]] or [
                a for a in cands if s["lecture"] and lecture_de(uid_docs, a["document"]) == s["lecture"]]
            if len(memes) == 1 and memes[0]["rattachement"]:
                s["amendement"] = memes[0]
                s["document"] = memes[0]["document"]
                cible = memes[0]["rattachement"]
                memes[0]["scrutin"] = s["numero"]
        if cible:
            s["impots"] = sorted(cible, key=[i["id"] for i in IMPOTS].index)
            retenus.append(s)
    print(f"  {len(retenus)} scrutins retenus", flush=True)

    # 4. amendements du Sénat adoptés, rattachés par code cité
    senat = amendements_senat()
    for a in senat:
        a["rattachement"] = {i: {"methode": "code_cite", "preuves": p} for i, p in
                             impots_cites(citations(texte_brut(a["dispositif"]))).items()}

    def auteur_publie(a: dict) -> dict:
        return {"type": a["auteur"]["type"], "nom": a["auteur"]["nom"], "groupe": a["auteur"]["groupe"]}

    def cle_nom(kv) -> tuple:
        """Ordre alphabétique du nom publié ; un identifiant sans nom dans la source passe en fin de liste."""
        return (nom_fr(nom_publie(kv[0]) or "~"), kv[0])

    sortie.mkdir(parents=True, exist_ok=True)
    for f in sortie.rglob("*.json"):
        f.unlink()
    ordre_groupes = lambda g: nom_fr(groupes.get(g, g))  # noqa: E731
    donnees_au = max((s["date"] for s in scr), default=None)
    entete = {"millesime": MILLESIME, "source": SRC, "donnees_au": donnees_au}
    comptes_impots = []
    tous_deputes_votants: set[str] = set()
    for imp in IMPOTS:
        iid = imp["id"]
        arts = []
        for (uid, et), r in sorted(rattach_articles.items(), key=lambda kv: (cle_tri_texte(textes[kv[0][0]]["cle"]),
                                                                           ordre_document(kv[0][0]),
                                                                           tri_article(kv[0][1]))):
            if iid not in r:
                continue
            t = textes[uid]
            a = t["articles"][et]
            arts.append({"texte": t["cle"], "texte_libelle": libelle_texte(t["cle"]), "lecture": t["lecture"],
                         "document": uid, "url_document": URL_TEXTE.format(uid=uid), "article": et,
                         "intitule": a["intitule"] or a.get("intitule_projet"),
                         "intitule_source": ("texte examiné" if a["intitule"] else
                                             "projet déposé" if a.get("intitule_projet") else None),
                         "extrait": extrait(a["alineas"]),
                         "rattachement": r[iid],
                         "scrutins": [s["numero"] for s in retenus if s.get("document") == uid
                                      and s["article"] == et]})
        scs, votes = [], {}
        for s in sorted((s for s in retenus if iid in s["impots"]),
                        key=lambda s: (cle_tri_texte(s["texte"]), s["numero"])):
            gs, vg = [], []
            for g in sorted(s["groupes"], key=lambda g: ordre_groupes(g["organe"])):
                gs.append({"groupe": groupes.get(g["organe"], g["organe"]), "membres": g["membres"],
                           **g["decompte"]})
                par_pos = {"pour": [], "contre": [], "abstention": [], "non_votant": []}
                deleg = []
                for pa, (p, _, d) in sorted(g["positions"].items(), key=cle_nom):
                    par_pos[p].append(pa)
                    tous_deputes_votants.add(pa)
                    if d:
                        deleg.append(pa)
                vg.append({"groupe": groupes.get(g["organe"], g["organe"]), **par_pos, "par_delegation": deleg})
            am = s.get("amendement")
            scs.append({"numero": s["numero"], "date": s["date"], "texte": s["texte"], "lecture": s["lecture"],
                        "objet": s["objet"], "type": "article" if s["article"] is not None else
                        "amendement", "article": s["article"], "amendement": am["numero_long"] if am else None,
                        "rattachement": (am["rattachement"][iid] if am else
                                         rattach_articles[(s["document"], s["article"])][iid]),
                        "resultat": s["resultat"], **s["decompte"], "nominatif": s["nominatif"],
                        "groupes": gs, "url": s["url"]})
            votes[str(s["numero"])] = {"groupes": vg, "mises_au_point": [
                {"depute": pa, "position_souhaitee": p}
                for pa, p in sorted(s["mises_au_point"].items(), key=cle_nom)]}
        ams = []
        for a in sorted((a for a in amdts + senat if a["sort"] == "Adopté" and iid in a.get("rattachement", {})),
                        key=lambda a: (a["date"] or "", a["chambre"] if "chambre" in a else "AN", a["numero"]),
                        reverse=True):
            ams.append({"chambre": a.get("chambre", "Assemblée nationale").replace("AN", "Assemblée nationale"),
                        "texte": a["texte"], "lecture": (lecture_de(docs[a["texte"]], a["document"])
                                                         if a.get("document") else None),
                        "numero": a["numero_long"], "article_vise": a["article_vise"], "date": a["date"],
                        "sort": a["sort"], "auteur": auteur_publie(a), "cosignataires": a["cosignataires"],
                        "dispositif": extrait(texte_brut(a["dispositif"]), 700), "rattachement": a["rattachement"][iid],
                        "scrutin": a.get("scrutin"),
                        "url": a.get("url") or URL_AMDT.format(uid=a["uid"])})
        deputes = sorted({pa for v in votes.values() for g in v["groupes"] for k in
                          ("pour", "contre", "abstention", "non_votant") for pa in g[k]}
                         | {m["depute"] for v in votes.values() for m in v["mises_au_point"]})
        dump(sortie / f"impot_{iid}.json", {
            **entete, "impot": {k: imp[k] for k in ("id", "libelle", "lignes_simulateur", "bases_texte")},
            "methode": METHODE, "avertissements": AVERTISSEMENTS, "regle_ordre": REGLE_ORDRE_LISTES,
            "regle_ordre_groupes": REGLE_ORDRE_GROUPES, "regle_personnes": REGLE_PERSONNES,
            "articles": arts, "scrutins": scs, "amendements_adoptes": ams, "fichier_votes": f"votes_{iid}.json"})
        dump(sortie / f"votes_{iid}.json", {
            **entete, "impot": iid, "regle_ordre_groupes": REGLE_ORDRE_GROUPES,
            "deputes": {pa: nom_publie(pa) for pa in deputes}, "votes": votes})
        comptes_impots.append({"id": iid, "libelle": imp["libelle"], "articles": len(arts), "scrutins": len(scs),
                               "amendements_adoptes": len(ams),
                               "amendements_adoptes_assemblee": sum(a["chambre"] == "Assemblée nationale" for a in ams),
                               "amendements_adoptes_senat": sum(a["chambre"] == "Sénat" for a in ams),
                               "fichier": f"impot_{iid}.json", "fichier_votes": f"votes_{iid}.json"})

    # 5. scrutins retenus (tous impôts) et votes par circonscription
    liste = [{"numero": s["numero"], "date": s["date"], "texte": s["texte"], "lecture": s["lecture"],
              "objet": s["objet"], "impots": s["impots"], "resultat": s["resultat"], "url": s["url"]}
             for s in sorted(retenus, key=lambda s: s["numero"])]
    dump(sortie / "scrutins.json", {**entete, "regle_ordre": "Scrutins par numéro (ordre chronologique).",
                                    "scrutins": liste})
    par_mandat = defaultdict(list)
    for s in sorted(retenus, key=lambda s: s["numero"]):
        for g in s["groupes"]:
            for pa, (p, mandat, d) in g["positions"].items():
                par_mandat[mandat or pa].append([s["numero"], p, 1 if d else 0, groupes.get(g["organe"], g["organe"]),
                                                 s["mises_au_point"].get(pa)])
        for pa, p in s["mises_au_point"].items():
            if not any(pa in g["positions"] for g in s["groupes"]):
                mandat = next((k for k, m in mandats.items() if m["acteur"] == pa and (m["debut"] or "") <= s["date"]
                               and (m["fin"] is None or s["date"] <= m["fin"])), pa)
                par_mandat[mandat].append([s["numero"], None, 0, None, p])
    departements = []
    par_dep = defaultdict(lambda: defaultdict(list))
    for pm, m in mandats.items():
        par_dep[m["num_departement"]][m["circonscription"]].append((pm, m))
    deputes_couverts = set()
    for dep in sorted(par_dep, key=lambda d: (len(d.lstrip("0")) > 2, d.zfill(3))):
        circos = []
        for c in sorted(par_dep[dep]):
            ds = []
            for pm, m in sorted(par_dep[dep][c], key=lambda x: (x[1]["debut"] or "", x[0])):
                deputes_couverts.add(m["acteur"])
                ds.append({"depute": m["acteur"], "nom": nom_publie(m["acteur"]),
                           "debut": m["debut"], "fin": m["fin"], "votes": par_mandat.get(pm, [])})
            circos.append({"numero": c, "deputes": ds})
        code = dep.lstrip("0").zfill(2) if dep.isdigit() and len(dep.lstrip("0")) <= 2 else dep.lstrip("0") or dep
        dump(sortie / "departements" / f"{code}.json", {
            **entete, "departement": {"code": code, "nom": deps[dep]}, "colonnes_votes":
                ["scrutin", "position", "par_delegation", "groupe", "mise_au_point"],
            "positions": {"pour": "pour", "contre": "contre", "abstention": "abstention", "non_votant": "non-votant",
                          "null": "aucune position enregistrée (mise au point seule)"},
            "circonscriptions": circos})
        departements.append({"code": code, "nom": deps[dep], "circonscriptions": [c["numero"] for c in circos],
                             "fichier": f"departements/{code}.json"})

    idx = {**entete,
           "presentation": ("Pour chaque impôt que le simulateur te montre : les articles des lois de finances et de "
                            "financement de la sécurité sociale qui l'ont fixé ou modifié pendant la 17e législature, "
                            "les scrutins publics correspondants avec le vote de chaque député, et les amendements "
                            "adoptés avec leur auteur. La page ne dit pas si une décision était bonne ou mauvaise."),
           "methode": METHODE, "avertissements": AVERTISSEMENTS, "regle_ordre": REGLE_ORDRE_LISTES,
           "regle_ordre_groupes": REGLE_ORDRE_GROUPES, "regle_personnes": REGLE_PERSONNES,
           "confidentialite": ("Le choix du département et de la circonscription se fait dans ton navigateur : rien "
                               "n'est envoyé ni conservé."),
           "impots": comptes_impots, "non_couverts": NON_COUVERTS,
           "correspondance_simulateur": LIBELLES_CONSO_SIMULATEUR,
           "textes_examines": [{"texte": cle, "texte_libelle": libelle_texte(cle), "documents": [
               {"document": u, "lecture": lecture_de(docs[cle], u), "url": URL_TEXTE.format(uid=u),
                "lu": u in textes} for u in docs[cle]]} for cle in sorted(docs, key=cle_tri_texte)],
           "departements": departements,
           "comptes": {"impots_couverts": sum(1 for c in comptes_impots if c["articles"] or c["scrutins"]
                                              or c["amendements_adoptes"]),
                       "scrutins_retenus": len(retenus),
                       "amendements_adoptes_nommes": len({(a["texte"], a.get("chambre", "AN"), a["numero"])
                                                           for a in amdts + senat if a["sort"] == "Adopté"
                                                           and a.get("rattachement") and a["auteur"]["type"]
                                                           not in ("gouvernement", "commission", "autre")
                                                           and a["auteur"]["nom"]}),
                       "deputes_votants": len(tous_deputes_votants), "deputes_circonscriptions": len(deputes_couverts),
                       "textes_non_retrouves": manquants},
           "limites": [
               "Scrutins publics de l'Assemblée nationale seulement : les votes à main levée ne sont pas nominatifs.",
               "Le Sénat ne publie pas ses scrutins nominatifs en données ouvertes (data.senat.fr, relevé du "
               "19/11/2026) : non repris.",
               "Amendements de séance publique seulement (les amendements adoptés en commission ne modifient pas le "
               "texte examiné en séance pour les lois financières).",
               "Les cotisations sociales ne sont pas couvertes : leurs taux sont fixés par décret."],
           "recherche_publique": {"date": "2026-11-19", "trouvailles": [
               {"nom": "pipeline/decisions.py (ce dépôt)", "verdict": "réutilisable tel quel",
                "detail": "lecteurs des zips de l'Assemblée et du dump Ameli"},
               {"nom": "NosDéputés.fr / Regards Citoyens (cpc-api)", "verdict": "inspiration seulement",
                "detail": "votes par député, licence ODbL ; pas de rattachement aux impôts ; données de l'Assemblée "
                          "lues directement ici"},
               {"nom": "LexImpact (Assemblée nationale)", "verdict": "inspiration seulement",
                "detail": "simulateur de réformes de l'impôt sur le revenu (AGPL-3.0) ; ne relie pas les votes"}]}}
    dump(sortie / "index.json", idx)
    print(json.dumps(idx["comptes"], ensure_ascii=False))
    return idx


# --- Collecte ---------------------------------------------------------------------------------------------------------


def _telecharger(url: str, dest: Path) -> None:
    import fetch
    r = fetch.get(url)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(r.content)
    fetch.remplacer_si_valide(tmp, dest, nom=dest.name, octets_attendus=fetch.octets_annonces(r))


def collecter() -> int:
    """Acteurs (AMO30) puis textes examinés en séance (liste tirée des amendements de séance). Refus 401/403/429 :
    arrêt sans contournement (fetch.get)."""
    ENTREPOT.mkdir(parents=True, exist_ok=True)
    TEXTES.mkdir(parents=True, exist_ok=True)
    _telecharger(URL_ACTEURS, ACTEURS)
    dos = dossiers()
    uids = set()
    with zipfile.ZipFile(D.AN_AMDTS) as z:
        for n in z.namelist():
            p = n.split("/")
            if len(p) >= 4 and p[1] in dos and SEANCE_AN in p[3]:
                uids.add(p[2])
    for uid in sorted(uids):
        dest = TEXTES / f"{uid}.html"
        if dest.exists():
            continue
        _telecharger(URL_TEXTE.format(uid=uid), dest)
        time.sleep(1)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = ap.add_subparsers(dest="commande", required=True)
    sous.add_parser("collecter")
    p = sous.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    if a.commande == "collecter":
        return collecter()
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
