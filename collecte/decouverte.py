"""Decouverte automatique des jeux de donnees ayant un lien avec l'argent public.

Parcourt :
  (a) les catalogues complets des portails Opendatasoft (data.economie.gouv.fr, data.ofgl.fr,
      DREES, data.caf.fr, data.ameli.fr) via /api/explore/v2.1/catalog/datasets pagine ;
  (b) data.gouv.fr via /api/1/datasets/, filtre par organisations publiques cles et par mots-cles.

Produit collecte/decouvertes.json : un enregistrement par jeu (id, portail, titre, producteur,
nb lignes, taille estimee, date de mise a jour, licence, score de pertinence, domaine presume,
drapeau personnes_physiques presume). Les jeux data.gouv.fr moissonnes depuis un portail ODS deja
parcouru sont marques doublon_de.

Usage :
  python collecte/decouverte.py                       # tout
  python collecte/decouverte.py --sans-datagouv       # portails ODS seulement
  python collecte/decouverte.py --pages-mot-cle 2     # profondeur de recherche data.gouv.fr
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collecte import (DATAGOUV_API, PORTAILS_SUPP_PATH, Client, charger_portails, ecrire_decouvertes,  # noqa: E402
                      lire_decouvertes, maintenant, nom_sur)

PORTAILS_ODS = ["economie", "ofgl", "drees", "caf", "ameli", "urssaf", "esr", "atih", "cdc"]
BONUS_PORTAIL = {"economie": 1, "ofgl": 2, "urssaf": 1}

# Organisations data.gouv.fr parcourues en entier (id -> (nom court, bonus de pertinence))
ORGANISATIONS = {
    "534fff8ea3a7292c64a77f02": ("Ministeres economiques et financiers (DGFiP, DB, AFT, DGE...)", 2),
    "534fff63a3a7292c64a77d67": ("CNCCFP", 3),
    "53ae7fb2a3a729709f56d4f0": ("HATVP", 3),
    "53698dada3a729239d20331d": ("Cour des comptes", 2),
    "5e145ef68b4c4135aa9b0b7a": ("DGCL", 2),
    "5b23863888ee381aef2b6a58": ("OFGL", 2),
    "5e9d6eaf7137453528ac7e9b": ("Urssaf", 2),
    "534fff5ca3a7292c64a77d1a": ("Caisse nationale de l'assurance maladie", 1),
    "5595066cc751df4582a453ba": ("Allocations familiales (CNAF)", 1),
    "66fabd290ae4c54492014989": ("Bpifrance", 2),
    "6ab4ee84781d4f04cf946298": ("Bpifrance Investissement", 2),
    "5901f4dfc751df412e7bb92d": ("ANCT", 1),
    "5fa985066333fad0e735c985": ("Caisse des depots", 1),
    "534fff4ea3a7292c64a77cae": ("Agence de services et de paiement", 2),
    "5be157a3634f4157841e6496": ("Direction des achats de l'Etat", 2),
    "534fff94a3a7292c64a77fc1": ("Ministere des Solidarites et de la Sante", 0),
    "55819607c751df7bdda453b9": ("Assemblee nationale", 1),
    "53a8b6eba3a72905b7ce595b": ("Senat", 1),
    "534fffa5a3a7292c64a7809e": ("Premier ministre", 0),
    "534fff59a3a7292c64a77cfd": ("Banque de France", 0),
    "534fff91a3a7292c64a77f53": ("Ministere de l'Interieur", 0),
    "534fffa3a3a7292c64a78094": ("France Travail", 1),
}

MOTS_CLES_RECHERCHE = [
    "budget", "subvention", "aide", "dépense", "marché public", "dotation", "compte", "financement",
    "campagne électorale", "parti politique", "fiscal", "impôt", "recette", "dette", "dépenses fiscales",
    "loi de finances", "aides d'État", "exonération", "fonds européens", "commande publique",
    "représentants d'intérêts", "comptes administratifs", "balance comptable", "taxe", "trésorerie",
    "compte administratif", "budget primitif", "subventions versées", "données essentielles marchés",
    "dotations de l'État", "indemnisation chômage", "rémunérations", "prestations sociales", "fonds social européen",
]

# motif (sur texte normalise sans accents) -> etiquette
MOTIFS = [
    (r"\bbudget", "budget"), (r"\bsubvention", "subvention"), (r"\baides?\b", "aide"),
    (r"\bdepense", "depense"), (r"\bmarches? publics?|\bcommande publique|\bdecp\b|\bachats?\b", "marche"),
    (r"\bdotation", "dotation"), (r"\bcomptes?\b|\bcomptab|\bbalances? comptable", "compte"),
    (r"\bfinanc", "financement"), (r"\bcampagnes? electorale|\bcomptes de campagne", "campagne"),
    (r"\bpartis? politique|\bfinancements? politique", "parti"), (r"\bfiscal", "fiscal"),
    (r"\bimpots?\b|\bimposition|\bimpot sur", "impot"), (r"\brecettes?\b", "recette"),
    (r"\bdette|\bemprunt", "dette"), (r"\btaxes?\b|\btva\b", "taxe"),
    (r"\bloi de finances|\bplf\b|\bplr\b|\bplrg\b|\blfi\b|\blfss\b", "loi_de_finances"),
    (r"\bcredits?\b", "credits"), (r"\bdeficit", "deficit"), (r"\btresor", "tresor"),
    (r"\bexoneration|\ballegement", "exoneration"), (r"\bcotisation|\bprelevement", "prelevement"),
    (r"\bfonds\b|\bfeder\b|\bfeader\b|\bfse\b|\bfeampa\b", "fonds"), (r"\binvestissement", "investissement"),
    (r"\brelance\b|\bfrance 2030\b|\bpia\b", "plan_public"), (r"representants? d.interets|\blobby", "lobbying"),
    (r"\bremuneration|\bsalaires?\b|\btraitements?\b", "remuneration"),
    (r"\bprestations?\b|\ballocations?\b", "prestation"), (r"\bmontants?\b|\beuros?\b", "montant"),
    (r"\bcollectivites?\b|\bcommunes?\b|\bdepartements?\b|\bintercommunal|\bregions?\b", "collectivite"),
    (r"\boperateurs?\b|\betablissements? publics?", "operateur"),
]
MOTIFS_C = [(re.compile(m), e) for m, e in MOTIFS]
FORTS = {"budget", "subvention", "aide", "depense", "marche", "dotation", "financement", "campagne", "parti",
         "fiscal", "impot", "recette", "dette", "taxe", "loi_de_finances", "deficit", "tresor", "exoneration",
         "prelevement", "fonds", "plan_public", "lobbying", "compte"}

DOMAINES = [  # (domaine, motifs) : premier qui correspond, sur le titre puis le texte
    ("politique", r"campagnes? electorale|comptes de campagne|partis? politique|financements? politique|"
                  r"representants? d.interets|\blobby|\bhatvp\b|\bcnccfp\b|\bcandidats?\b"),
    ("europe", r"\beurop|\bfeder\b|\bfeader\b|\bfse\b|kohesio|\bue\b"),
    ("dette", r"\bdette|\bemprunt|\btresor\b|\boat\b|agence france tresor"),
    ("fiscalite", r"\bimpot|\bfiscal|\btaxe|\btva\b|\bdgfip\b|\bniche|\bimposition|\bcontribuable"),
    ("secu", r"securite sociale|\bsante\b|maladie|\bcaf\b|\burssaf|\bretraite|allocations? familiales|\bprestations? sociales|\bhopita|\bdrees\b|\bameli\b|\bcnam|\bcotisation"),
    ("collectivites", r"collectivit|\bcommunes?\b|departement|\bregions?\b|intercommunal|\bepci\b|\bdgcl\b|\bofgl\b|\bdotation|\blocales?\b"),
    ("beneficiaires", r"subvention|\baides?\b|marches? publics?|commande publique|\bdecp\b|associations?|entreprises?|beneficiaire|relance|france 2030|bpifrance|\bminimis\b"),
    ("etat", r"\betat\b|loi de finances|\bplf\b|\bplr\b|\blfi\b|ministere|programme|\bmission|\bbudget"),
]
DOMAINES_C = [(d, re.compile(m)) for d, m in DOMAINES]

PP_JETONS = {"prenom", "prenoms", "civilite", "naissance", "datenaissance", "nomnaissance", "nom_naissance"}
PP_NOM_SUFFIXES = ("beneficiaire", "candidat", "elu", "declarant", "titulaire", "dirigeant", "representant",
                   "usage", "famille", "personne", "mandataire", "president", "tresorier", "responsable")
PP_TEXTE = re.compile(r"nominati|\bcandidats?\b|\belus?\b|declarations? d.interets|representants? d.interets|"
                      r"\bdirigeants?\b|\bpersonnes? physiques?|\bprenoms?\b|\bmandataires?\b")


def normaliser(texte: str | None) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[’']", "'", t)


def etiquettes(texte: str) -> set[str]:
    return {e for m, e in MOTIFS_C if m.search(texte)}


def score_pertinence(titre: str, autres: str, bonus: float = 0) -> tuple[float, list[str]]:
    """3 points par etiquette forte dans le titre, 1 par etiquette faible dans le titre,
    1 par etiquette forte ailleurs seulement (plafond 4), plus le bonus portail/producteur."""
    et_t = etiquettes(normaliser(titre))
    et_a = etiquettes(normaliser(autres)) - et_t
    s = sum(3 if e in FORTS else 1 for e in et_t) + min(4, sum(1 for e in et_a if e in FORTS))
    if not et_t and not (et_a & FORTS):
        bonus = min(bonus, 1)  # un producteur pertinent ne suffit pas a rendre pertinent un jeu sans lien
    return float(s + bonus), sorted(et_t | et_a)


def domaine_presume(titre: str, autres: str) -> str:
    for texte in (normaliser(titre), normaliser(autres)):
        for d, m in DOMAINES_C:
            if m.search(texte):
                return d
    return "divers"


def champ_personne(nom: str, label: str = "") -> bool:
    for brut in (nom, normaliser(label).replace(" ", "_")):
        n = normaliser(brut)
        jetons = set(re.split(r"[^a-z0-9]+", n))
        if jetons & PP_JETONS:
            return True
        if n in ("nom", "nom_s", "noms") or (n.startswith("nom_") and n[4:].startswith(PP_NOM_SUFFIXES)):
            return True
    return False


def personnes_physiques_ods(champs: list[dict]) -> tuple[bool, list[str]]:
    trouves = [c["name"] for c in champs or [] if champ_personne(c.get("name", ""), c.get("label") or "")]
    return bool(trouves), trouves


# ---------------------------------------------------------------- ODS

def lire_catalogue_ods(client: Client, base: str, par_page: int = 100) -> list[dict]:
    jeux, offset, total = [], 0, None
    while total is None or offset < total:
        d = client.json(f"{base}/api/explore/v2.1/catalog/datasets",
                        params={"limit": par_page, "offset": offset})
        total = d.get("total_count", 0)
        lot = d.get("results", [])
        if not lot:
            break
        jeux.extend(lot)
        offset += len(lot)
        if offset >= 10000:  # limite de pagination ODS
            break
    return jeux


def jeu_ods(portail: str, base: str, r: dict) -> dict:
    m = r.get("metas", {}).get("default", {})
    titre = m.get("title") or r["dataset_id"]
    autres = " ".join([" ".join(m.get("keyword") or []), " ".join(m.get("theme") or []), (m.get("description") or "")[:1500]])
    score, et = score_pertinence(titre, autres, BONUS_PORTAIL.get(portail, 0))
    pp, champs_pp = personnes_physiques_ods(r.get("fields"))
    n = m.get("records_count") or 0
    nb_champs = len(r.get("fields") or [])
    geo = any((c.get("type") in ("geo_shape", "geo_point_2d")) for c in r.get("fields") or [])
    # estimation grossiere parquet ; une geometrie (geo_shape) pese des centaines d'octets par ligne
    taille = round(n * (max(nb_champs, 1) * 8 + (600 if geo else 0)) / 1e6, 2) if n else None
    return {
        "id": nom_sur(f"{portail}__{r['dataset_id']}", 120), "portail": portail, "dataset": r["dataset_id"],
        "url": f"{base}/explore/dataset/{r['dataset_id']}/", "titre": titre, "producteur": m.get("publisher"),
        "nb_lignes": n, "nb_champs": nb_champs, "nb_pieces_jointes": len(r.get("attachments") or []),
        "taille_estimee_mo": taille, "mis_a_jour": m.get("modified") or m.get("data_processed"),
        "licence": m.get("license"), "score": score, "etiquettes": et,
        "domaine": domaine_presume(titre, autres), "personnes_physiques": pp, "pp_motif": champs_pp[:10],
        "lourd": bool(taille and taille > 100),
    }


# ---------------------------------------------------------------- data.gouv.fr

def pages_datagouv(client: Client, params: dict, max_pages: int | None = None, par_page: int = 100):
    page = 1
    while True:
        d = client.json(f"{DATAGOUV_API}/datasets/", params={**params, "page": page, "page_size": par_page})
        for x in d.get("data", []):
            yield x
        if not d.get("next_page") or (max_pages and page >= max_pages):
            break
        page += 1


def jeu_datagouv(d: dict, hotes_ods: dict) -> dict | None:
    if d.get("archived") or d.get("deleted") or d.get("private"):
        return None
    org = d.get("organization") or {}
    oid = org.get("id")
    titre = d.get("title") or d["id"]
    autres = " ".join([" ".join(d.get("tags") or []), (d.get("description") or "")[:1500]])
    score, et = score_pertinence(titre, autres, ORGANISATIONS.get(oid, ("", 0))[1])
    principales = [r for r in d.get("resources", []) if r.get("type", "main") == "main"]
    tailles = [r.get("filesize") for r in principales if r.get("filesize")]
    taille = round(sum(tailles) / 1e6, 2) if tailles else None
    texte_pp = normaliser(titre + " " + autres)
    pp = bool(PP_TEXTE.search(texte_pp))
    h = d.get("harvest") or {}
    doublon = None
    if h.get("domain") in hotes_ods:
        m = re.search(r"/dataset/([^/?#]+)", h.get("remote_id") or h.get("remote_url") or "")
        if m:
            doublon = f"{hotes_ods[h['domain']]}__{m.group(1)}"
    return {
        "id": nom_sur(f"datagouv__{d.get('slug') or d['id']}", 120), "portail": "datagouv", "dataset": d["id"],
        "url": d.get("page"), "titre": titre, "producteur": org.get("name") or (d.get("owner") or {}).get("slug"),
        "organisation_id": oid, "nb_lignes": None, "nb_ressources": len(principales),
        "formats": sorted({(r.get("format") or "?").lower() for r in principales}),
        "taille_estimee_mo": taille, "mis_a_jour": d.get("last_update") or d.get("last_modified"),
        "licence": d.get("license"), "score": score, "etiquettes": et,
        "domaine": domaine_presume(titre, autres), "personnes_physiques": pp,
        "pp_motif": ["mots du titre ou de la description"] if pp else [],
        "lourd": bool(taille and taille > 100), "doublon_de": doublon,
    }


# ---------------------------------------------------------------- programme

def portails_ods_tous(portails: dict) -> list[str]:
    supp = json.loads(PORTAILS_SUPP_PATH.read_text(encoding="utf-8"))["portails"] if PORTAILS_SUPP_PATH.exists() else {}
    return PORTAILS_ODS + [k for k in supp if k not in PORTAILS_ODS]


def decouvrir(client: Client, portails: dict, avec_datagouv: bool = True, pages_mot_cle: int = 3,
              journal=print, seulement: list[str] | None = None, precedent: dict | None = None,
              paralleles: int = 8) -> dict:
    """seulement : liste de portails a (re)parcourir ; les jeux des autres portails sont repris de `precedent`."""
    jeux: dict[str, dict] = {}
    comptes = Counter((precedent or {}).get("comptes_bruts", {}))
    if seulement and precedent:
        a_refaire = set(seulement) | ({"datagouv"} if avec_datagouv else set())
        jeux = {j["id"]: j for j in precedent["jeux"] if j["portail"] not in a_refaire}
    hotes_ods = {portails[p].split("//", 1)[1]: p for p in portails_ods_tous(portails) if p in portails}
    from concurrent.futures import ThreadPoolExecutor

    def un_portail(p):
        # un client par portail : jamais deux appels simultanes vers le meme hote
        try:
            return p, lire_catalogue_ods(Client(pause=client.pause), portails[p]), None
        except Exception as exc:
            return p, [], exc

    a_lire = [p for p in portails_ods_tous(portails) if not seulement or p in seulement]
    with ThreadPoolExecutor(max_workers=paralleles) as ex:
        for p, brut, exc in ex.map(un_portail, a_lire):
            if exc:
                journal(f"ERREUR catalogue {p} : {exc}")
                continue
            for r in brut:
                j = jeu_ods(p, portails[p], r)
                jeux[j["id"]] = j
            comptes[p] = len(brut)
            journal(f"{p:<10} {len(brut):>5} jeux")
    if avec_datagouv:
        vus = set()
        requetes = [({"organization": o}, None, f"org {n}") for o, (n, _) in ORGANISATIONS.items()]
        requetes += [({"q": q}, pages_mot_cle, f"mot-cle {q}") for q in MOTS_CLES_RECHERCHE]
        for params, max_pages, libelle in requetes:
            n = 0
            try:
                for d in pages_datagouv(client, params, max_pages):
                    n += 1
                    if d["id"] in vus:
                        continue
                    vus.add(d["id"])
                    j = jeu_datagouv(d, hotes_ods)
                    if j:
                        jeux[j["id"]] = j
            except Exception as exc:
                journal(f"ERREUR data.gouv.fr {libelle} : {exc}")
            journal(f"datagouv   {n:>5} resultats ({libelle})")
        comptes["datagouv"] = len(vus)
    liste = sorted(jeux.values(), key=lambda j: (-j["score"], j["portail"], j["id"]))
    return {
        "_lisez_moi": "Genere par collecte/decouverte.py. score = pertinence 'argent public' (mots-cles du titre, "
                      "des mots-cles et de la description, bonus portail/producteur). personnes_physiques = presomption "
                      "(champs nom/prenom pour ODS, vocabulaire pour data.gouv.fr) a confirmer. doublon_de = jeu moissonne "
                      "depuis un portail ODS deja parcouru. Tailles estimees.",
        "genere_le": maintenant(), "comptes_bruts": dict(comptes), "nb_jeux": len(liste),
        "jeux": liste,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sans-datagouv", action="store_true")
    ap.add_argument("--pages-mot-cle", type=int, default=3, help="pages de 100 resultats par mot-cle data.gouv.fr")
    ap.add_argument("--pause", type=float, default=0.3)
    ap.add_argument("--portail", action="append", help="ne reparcourir que ce portail ODS (repetable), les autres sont repris")
    a = ap.parse_args(argv)
    res = decouvrir(Client(pause=a.pause), charger_portails(), not a.sans_datagouv, a.pages_mot_cle,
                    seulement=a.portail, precedent=lire_decouvertes())
    chemin = ecrire_decouvertes(res)
    sc = Counter(int(j["score"] >= 4) for j in res["jeux"])
    print(f"{res['nb_jeux']} jeux decouverts, {sc[1]} avec score >= 4, ecrit dans {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
