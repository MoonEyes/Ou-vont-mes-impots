"""Aide au développement : par pays, par secteur, par instrument, par année, grandeur par grandeur.

Plusieurs grandeurs décrivent l'aide au développement de la France ; elles ne mesurent pas la même chose et ne
sont JAMAIS additionnées entre elles, ni les dons avec les prêts :

    crédits budgétaires   mission « Aide publique au développement » du budget de l'État (site/data/arbre)
    APD déclarée          aide publique au développement déclarée par la France au CAD de l'OCDE, activité par
                          activité (DG Trésor, data.economie.gouv.fr), en euros, tous organismes publics
    activité de l'AFD     concours de l'Agence française de développement (standard IATI) : dons et prêts,
                          engagements et versements
    Proparco              financements signés par la filiale du groupe AFD pour le secteur privé
    Expertise France      contrats de plus de 15 000 euros (plafonds et montants maximaux, pas des dépenses)
    OCDE                  tables DAC2A (versements par pays) et DAC5 (engagements par secteur), dollars courants

Commandes :
    python collecte/collecte.py etat_aide_publique_developpement apd_afd_iati apd_ocde_dac2a apd_ocde_dac5 \
        apd_expertise_france_contrats apd_proparco      (réseau ; un refus 403/429 n'est jamais contourné)
    python pipeline/aide_developpement.py produire [--sortie DOSSIER]   (sans réseau)

Sorties (site/data/aide_developpement/, schémas docs/schemas/aide_developpement_*.schema.json) :
    index.json, apd_declaree.json, afd.json, ocde.json, expertise_france.json, proparco.json

Confidentialité : aucun nom de bénéficiaire, d'attributaire, de client ni d'expert n'est lu pour être publié ; les
colonnes de texte libre (titres, descriptions, objets) et de contact ne sont jamais chargées. Les contrats
d'experts individuels d'Expertise France (personnes physiques) sont exclus des ventilations et comptés une seule
fois, en total, dans `ecartes`. Sorties reproductibles : dates lues dans le manifeste de collecte, ordres explicites.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproductible import date_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "lake"
DOM = LAKE / "aide_developpement"
SITE = ROOT / "site" / "data"
SORTIE = SITE / "aide_developpement"
MANIFESTE = LAKE / "manifest.json"

F_ETAT = LAKE / "etat" / "etat_aide_publique_developpement.parquet"
D_IATI = DOM / "apd_afd_iati"
F_DAC2A = DOM / "apd_ocde_dac2a.csv"
F_DAC5 = DOM / "apd_ocde_dac5.csv"
F_EF = LAKE / "_restreint" / "aide_developpement" / "apd_expertise_france_contrats.csv"
F_PROPARCO = DOM / "apd_proparco.csv"

LIC_OCDE = ("CC BY 4.0 (accès ouvert de l'OCDE depuis le 1er juillet 2024) ; la page des conditions d'utilisation de "
            "l'OCDE a refusé la lecture par script (403) le 17/11/2026 et n'a pas été contournée")
LIC_AFD_NP = ("non précisée par le producteur (data.gouv.fr : « notspecified » ; portail de l'AFD : champ vide) ; "
              "informations publiques réutilisables avec mention de la source (code des relations entre le public et "
              "l'administration, article L. 321-1)")
SOURCES = {
    "etat_aide_publique_developpement": {
        "nom": "DG Trésor, « Aide publique au développement » : activités déclarées par la France au CAD de l'OCDE",
        "url": "https://data.economie.gouv.fr/explore/dataset/aide-publique-au-developpement/",
        "licence": "Licence Ouverte 2.0", "producteur": "Direction générale du Trésor"},
    "apd_afd_iati": {
        "nom": "AFD, « Données de l'aide au développement de l'AFD » (standard IATI 2.03, un fichier par pays)",
        "url": "https://www.data.gouv.fr/datasets/donnees-de-laide-au-developpement-de-lafd-1/",
        "licence": "Licence Ouverte (data.gouv.fr) ; le jeu « les-projets-de-l-afd » du portail opendata.afd.fr, tiré "
                   "de la même publication IATI, ne porte aucune licence dans ses métadonnées",
        "producteur": "Agence française de développement"},
    "apd_ocde_dac2a": {
        "nom": "OCDE, CAD, table DAC2A : versements d'APD aux pays et régions (donneur : France)",
        "url": "https://sdmx.oecd.org/public/rest/data/OECD.DCD.FSD,DSD_DAC2@DF_DAC2A,/FRA...USD.V",
        "licence": LIC_OCDE, "producteur": "OCDE, Direction de la coopération pour le développement"},
    "apd_ocde_dac5": {
        "nom": "OCDE, CAD, table DAC5 : engagements d'APD bilatérale par secteur (donneur : France)",
        "url": "https://sdmx.oecd.org/public/rest/data/OECD.DCD.FSD,DSD_DAC1@DF_DAC5,/FRA.....USD.V",
        "licence": LIC_OCDE, "producteur": "OCDE, Direction de la coopération pour le développement"},
    "apd_expertise_france_contrats": {
        "nom": "Expertise France, contrats d'achat et de subvention de plus de 15 000 euros (coopération technique)",
        "url": "https://opendata.afd.fr/explore/dataset/donnees-des-contrats-dachats-et-de-subventions-dun-montant-"
               "superieur-a-15-000-ef/",
        "licence": LIC_AFD_NP, "producteur": "Expertise France (groupe AFD)"},
    "apd_proparco": {
        "nom": "Proparco, « Données de l'aide au développement de Proparco » (financements signés)",
        "url": "https://opendata.afd.fr/explore/dataset/donnees-de-laide-au-developpement-de-proparco/",
        "licence": LIC_AFD_NP, "producteur": "Proparco (groupe AFD)"},
}

REGLE = ("Les grandeurs de ce dossier ne s'additionnent pas. Crédits budgétaires de l'État, aide publique au "
         "développement déclarée à l'OCDE, concours de l'AFD, financements de Proparco et contrats d'Expertise France "
         "se recouvrent en partie et n'ont ni le même périmètre ni la même unité. Dons et prêts sont toujours donnés "
         "dans des colonnes séparées, sans total commun : un don n'est pas remboursé, un prêt l'est.")
FINANCEMENT_PRETS = ("Selon l'AFD, ses prêts sont financés pour l'essentiel par des emprunts obligataires sur les "
                     "marchés financiers et remboursés par les emprunteurs, et non par l'impôt. Le budget de l'État y "
                     "contribue par des bonifications d'intérêts (programme 110) et par des apports en fonds propres "
                     "(programme 365). Les dons de l'AFD viennent de crédits budgétaires (programme 209 surtout) ou "
                     "de fonds délégués par d'autres bailleurs, dont l'Union européenne.")

# ISO 3166-1 : code à deux lettres (fichiers IATI de l'AFD) -> code à trois lettres (DG Trésor, OCDE).
ISO2_ISO3 = dict(p.split(":") for p in (
    "AF:AFG AG:ATG AL:ALB AM:ARM AO:AGO AR:ARG AZ:AZE BA:BIH BB:BRB BD:BGD BF:BFA BI:BDI BJ:BEN BL:BLM BO:BOL BR:BRA "
    "BW:BWA BY:BLR CD:COD CF:CAF CG:COG CI:CIV CK:COK CL:CHL CM:CMR CN:CHN CO:COL CR:CRI CU:CUB CV:CPV DJ:DJI DM:DMA "
    "DO:DOM DZ:DZA EC:ECU EG:EGY ER:ERI ET:ETH FJ:FJI FM:FSM FR:FRA GA:GAB GB:GBR GD:GRD GE:GEO GF:GUF GH:GHA GM:GMB "
    "GN:GIN GP:GLP GQ:GNQ GT:GTM GW:GNB GY:GUY HN:HND HT:HTI ID:IDN IN:IND IO:IOT IQ:IRQ IR:IRN JM:JAM JO:JOR KE:KEN "
    "KG:KGZ KH:KHM KI:KIR KM:COM KN:KNA KZ:KAZ LA:LAO LB:LBN LC:LCA LK:LKA LR:LBR LS:LSO LY:LBY MA:MAR MD:MDA ME:MNE "
    "MF:MAF MG:MDG MH:MHL MK:MKD ML:MLI MM:MMR MN:MNG MQ:MTQ MR:MRT MU:MUS MV:MDV MW:MWI MX:MEX MY:MYS MZ:MOZ NA:NAM "
    "NE:NER NG:NGA NI:NIC NP:NPL NR:NRU NU:NIU PA:PAN PE:PER PF:PYF PG:PNG PH:PHL PK:PAK PN:PCN PS:PSE PW:PLW PY:PRY "
    "RE:REU RS:SRB RW:RWA SB:SLB SC:SYC SD:SDN SL:SLE SN:SEN SO:SOM SR:SUR SS:SSD ST:STP SV:SLV SY:SYR SZ:SWZ TD:TCD "
    "TF:ATF TG:TGO TH:THA TJ:TJK TK:TKL TL:TLS TN:TUN TO:TON TR:TUR TV:TUV TZ:TZA UA:UKR UG:UGA UY:URY UZ:UZB VC:VCT "
    "VE:VEN VN:VNM VU:VUT WF:WLF WS:WSM XK:XKX YE:YEM YT:MYT ZA:ZAF ZM:ZMB ZW:ZWE NC:NCL PM:SPM BT:BTN BZ:BLZ MS:MSR "
    "SH:SHN TM:TKM KP:PRK").split())
# Noms français des codes absents du jeu de la DG Trésor (qui fournit les autres noms).
NOMS_FR = {
    "ATF": "Terres australes françaises", "BLM": "Saint-Barthélemy", "BRB": "Barbade", "CHL": "Chili", "FRA": "France",
    "GBR": "Royaume-Uni", "GLP": "Guadeloupe", "GUF": "Guyane", "IOT": "Territoire britannique de l'océan Indien",
    "KNA": "Saint-Christophe-et-Niévès", "MAF": "Saint-Martin (partie française)", "MTQ": "Martinique",
    "MYT": "Mayotte", "NCL": "Nouvelle-Calédonie", "NIU": "Niue", "PCN": "Pitcairn", "PYF": "Polynésie française",
    "REU": "La Réunion", "SPM": "Saint-Pierre-et-Miquelon", "SYC": "Seychelles", "TKL": "Tokelau", "URY": "Uruguay",
    "XKX": "Kosovo", "XKV": "Kosovo", "ACP": "ACP", "PRK": "Corée du Nord", "TKM": "Turkménistan", "MSR": "Montserrat",
    "SHN": "Sainte-Hélène", "BLZ": "Belize", "BTN": "Bhoutan", "MYS": "Malaisie", "COK": "Îles Cook",
    "FSM": "Micronésie",
}

# DG Trésor : type de financement -> famille d'instrument (dons et prêts ne sont jamais réunis).
FAMILLES = {"Dons": "don", "Prêt": "pret"}
MESURES_DAC2A = [  # (code OCDE, clé publiée, libellé)
    ("201", "dons", "Dons d'APD, versements"),
    ("204", "prets_bruts", "Prêts d'APD, versements bruts"),
    ("205", "remboursements_prets", "Remboursements de prêts d'APD (valeurs négatives)"),
    ("218", "prets_nets", "Prêts d'APD, versements nets des remboursements"),
    ("240", "apd_brute", "APD brute (publiée par l'OCDE)"),
    ("206", "apd_nette", "APD, versements nets (publiée par l'OCDE)"),
    ("106", "multilaterale_imputee", "APD multilatérale imputée au pays (estimation de l'OCDE)"),
]
MESURES_DAC5 = [
    ("528", "engagements_apd", "Engagements d'APD bilatérale (dons et prêts, publiés ensemble par l'OCDE)"),
    ("529", "dont_dons", "dont dons d'APD bilatérale"),
    ("530", "autres_apports_publics", "Autres apports du secteur public, bilatéraux (hors APD)"),
]
SECTEURS_DAC5 = {
    "1000": "Tous secteurs", "450": "Total ventilable par secteur", "100": "Infrastructures et services sociaux",
    "110": "Éducation", "111": "Éducation, niveau non spécifié", "112": "Éducation de base",
    "113": "Éducation secondaire", "114": "Éducation post-secondaire", "120": "Santé", "121": "Santé, général",
    "122": "Santé de base", "123": "Maladies non transmissibles", "130": "Politique de population et santé "
    "reproductive", "139": "Santé et politique de population", "140": "Eau et assainissement",
    "150": "Gouvernement et société civile", "151": "Gouvernement et société civile, général",
    "152": "Conflits, paix et sécurité", "160": "Autres infrastructures et services sociaux",
    "200": "Infrastructures et services économiques", "210": "Transports et entreposage", "220": "Communications",
    "230": "Énergie", "240": "Banques et services financiers", "250": "Entreprises et autres services",
    "300": "Secteurs de production", "310": "Agriculture, sylviculture, pêche", "311": "Agriculture",
    "312": "Sylviculture", "313": "Pêche", "320": "Industries manufacturières, extractives, construction",
    "321": "Industries manufacturières", "322": "Ressources minérales et industries extractives",
    "323": "Construction", "331": "Politique commerciale et réglementations", "332": "Tourisme",
    "400": "Multisecteur", "410": "Protection de l'environnement", "430": "Autres multisecteurs",
    "500": "Aide sous forme de produits et aide-programme générale", "510": "Soutien budgétaire général",
    "520": "Aide alimentaire à des fins de développement", "530": "Autre aide sous forme de produits",
    "600": "Actions se rapportant à la dette", "700": "Aide humanitaire", "720": "Intervention d'urgence",
    "730": "Reconstruction et réhabilitation", "740": "Prévention des catastrophes et préparation",
    "998": "Non affecté, non spécifié",
}
ACTES_EF = {"Marché": "marche", "Marché subséquent": "marche_subsequent", "Subvention": "subvention",
            "Accord cadre": "accord_cadre"}
ACTE_EXCLU_EF = "Expert individuel (CPS)"
INSTANTANE_IATI = "dans_les_Etats_Etrangers"  # instantané d'ensemble du 09/01/2023, remplacé par les fichiers par pays

RECHERCHE_PUBLIQUE = {
    "date": "2026-11-17",
    "conclusion": "Les producteurs publient déjà les données nécessaires (DG Trésor, AFD au standard IATI, OCDE par "
                  "API SDMX) : elles sont reprises telles quelles avec le collecteur du dépôt. Aucun dépôt public "
                  "trouvé ne sépare dons et prêts de l'AFD ni ne relie ces sources à la mission budgétaire : module "
                  "écrit pour le dépôt, sur le modèle de pipeline/europe_comparaison.py.",
    "trouvailles": [
        {"nom": "DG Trésor, jeu « aide-publique-au-developpement » (déjà au catalogue du dépôt)",
         "url": SOURCES["etat_aide_publique_developpement"]["url"], "verdict": "réutilisable tel quel",
         "licence": "Licence Ouverte 2.0", "mise_a_jour": "déclarations 2018 à 2024"},
        {"nom": "AFD, publication IATI par pays (data.gouv.fr)", "url": SOURCES["apd_afd_iati"]["url"],
         "verdict": "réutilisable tel quel", "licence": "Licence Ouverte", "mise_a_jour": "2026-10-26"},
        {"nom": "AFD, jeu « les-projets-de-l-afd » (opendata.afd.fr)",
         "url": "https://opendata.afd.fr/explore/dataset/les-projets-de-l-afd/", "verdict": "inspiration seulement",
         "licence": "aucune licence dans les métadonnées ; un montant par projet, dons et prêts confondus quand un "
                    "projet réunit les deux", "mise_a_jour": "2026-11-17"},
        {"nom": "OCDE, API SDMX (DAC2A, DAC5)", "url": "https://sdmx.oecd.org/public/rest/",
         "verdict": "réutilisable tel quel", "licence": LIC_OCDE, "mise_a_jour": "données 2015 à 2024"},
        {"nom": "ONEcampaign/oda_reader (lecture des tables du CAD)", "url": "https://github.com/ONEcampaign/oda_reader",
         "verdict": "inspiration seulement", "licence": "MIT",
         "mise_a_jour": "2026-11-04 (non utilisé : deux requêtes SDMX suffisent, sans dépendance nouvelle)"},
        {"nom": "ONEcampaign/oda_data_package", "url": "https://github.com/ONEcampaign/oda_data_package",
         "verdict": "inspiration seulement", "licence": "MIT", "mise_a_jour": "2026-10-28"},
        {"nom": "codeforIATI/iatikit (lecture de fichiers IATI)", "url": "https://github.com/codeforIATI/iatikit",
         "verdict": "à adapter", "licence": "MIT",
         "mise_a_jour": "2025-10-23 (non utilisé : la bibliothèque standard lit les 95 fichiers)"},
        {"nom": "IATI/pyIATI", "url": "https://github.com/IATI/pyIATI", "verdict": "inspiration seulement",
         "licence": "MIT", "mise_a_jour": "2022-07-06 (archivé, abandonné)"},
        {"nom": "dr-leo/pandaSDMX", "url": "https://github.com/dr-leo/pandaSDMX", "verdict": "inspiration seulement",
         "licence": "Apache-2.0", "mise_a_jour": "2023-12-28"},
        {"nom": "collecte/collecte.py (collecteur du dépôt)", "url": "collecte/collecte.py",
         "verdict": "réutilisable tel quel", "licence": "MIT", "mise_a_jour": "2026-11-17"},
    ],
}


# ----------------------------------------------------------------------------------------------------- utilitaires

def nom_tri(nom: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", nom) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()


def _eur(x) -> int | None:
    """Arrondi à l'euro ; None reste None (donnée absente, jamais 0)."""
    return None if x is None else int(round(x + 0.0))


def _somme(d: dict, cle) -> float | None:
    return d.get(cle)


class Cumul:
    """Sommes par clé qui distinguent « aucune valeur publiée » (None) de 0."""

    def __init__(self):
        self.v: dict = {}

    def ajouter(self, cle, x) -> None:
        if x is None or x != x:  # None ou NaN : valeur absente à la source
            return
        self.v[cle] = self.v.get(cle, 0.0) + float(x)

    def get(self, cle):
        return self.v.get(cle)


def _collectes() -> dict:
    """Date de collecte de chaque source (manifeste de l'entrepôt) : reproductible à entrepôt constant."""
    try:
        m = json.loads(MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    return {sid: str((m.get(sid) or {}).get("collecte_le") or "")[:10] or None for sid in SOURCES}


def _ecrire(chemin: Path, doc: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ----------------------------------------------------------------------------------- APD déclarée (DG Trésor)

COLONNES_ETAT = ["annee_de_declaration", "agence", "code_du_pays_beneficiaire", "pays_beneficiaire", "categorie_cad",
                 "region", "codes_iso", "bi_multi0", "code_type_de_flux", "type_de_flux", "code_type_de_financement",
                 "type_de_financement", "code_objet", "secteur", "engagements_k_eur", "montant_verse_k_eur",
                 "montant_verse_k_usd", "equivalent_don_k_eur", "montant_percu_k_eur"]
FLUX_APD = "Aide Publique au Développement"


def lire_etat():
    """Lignes du jeu de la DG Trésor, colonnes utiles seulement (aucun texte libre, aucun numéro de projet)."""
    import pyarrow.parquet as pq
    t = pq.read_table(F_ETAT, columns=COLONNES_ETAT).to_pylist()
    for l in t:
        l["annee"] = int(str(l["annee_de_declaration"])[:4])
        for k, v in list(l.items()):
            if isinstance(v, float) and v != v:
                l[k] = None
        iso = l["codes_iso"]
        l["code"] = iso if iso and re.fullmatch(r"[A-Z]{3}", iso) else f"R{l['code_du_pays_beneficiaire']}"
    return t


def secteurs_cad(lignes) -> dict:
    """Préfixe à trois chiffres du code-objet du CAD -> libellé de secteur de la DG Trésor (le plus fréquent)."""
    comptes = defaultdict(lambda: defaultdict(int))
    for l in lignes:
        if l["code_objet"] and l["secteur"]:
            comptes[str(l["code_objet"])[:3]][l["secteur"]] += 1
    return {p: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for p, c in sorted(comptes.items())}


def produire_declaree(lignes, collecte) -> tuple[dict, dict]:
    annees = sorted({l["annee"] for l in lignes})
    k = 1000.0  # la source est en milliers d'euros
    par_annee, par_agence, par_pays, par_secteur, par_canal = Cumul(), Cumul(), Cumul(), Cumul(), Cumul()
    n_lignes = defaultdict(int)
    pays, usd = {}, Cumul()
    for l in lignes:
        a, fam = l["annee"], FAMILLES.get(l["type_de_financement"], "autre")
        cle = (a, l["type_de_flux"], l["type_de_financement"])
        n_lignes[cle] += 1
        for champ, col in (("engagements", "engagements_k_eur"), ("verse", "montant_verse_k_eur"),
                           ("equivalent_don", "equivalent_don_k_eur"), ("percu", "montant_percu_k_eur")):
            par_annee.ajouter(cle + (champ,), None if l[col] is None else l[col] * k)
        if l["type_de_flux"] != FLUX_APD:
            continue
        v = None if l["montant_verse_k_eur"] is None else l["montant_verse_k_eur"] * k
        ed = None if l["equivalent_don_k_eur"] is None else l["equivalent_don_k_eur"] * k
        pe = None if l["montant_percu_k_eur"] is None else l["montant_percu_k_eur"] * k
        for cumul, cle2 in ((par_agence, (a, l["agence"])), (par_pays, (a, l["code"])),
                            (par_secteur, (a, l["secteur"] or "Non spécifié")), (par_canal, (a, l["bi_multi0"]))):
            cumul.ajouter(cle2 + (fam,), v)
            cumul.ajouter(cle2 + ("equivalent_don",), ed)
            cumul.ajouter(cle2 + ("percu",), pe)
        if l["bi_multi0"] != "Multilatéral" and l["montant_verse_k_usd"] is not None:
            usd.ajouter((a, fam), l["montant_verse_k_usd"] / 1000.0)  # millions de dollars, pour l'écart avec l'OCDE
        if l["code"] not in pays:
            pays[l["code"]] = {"code": l["code"], "nom": l["pays_beneficiaire"], "nom_tri": nom_tri(l["pays_beneficiaire"]),
                               "type": "pays" if not l["code"].startswith("R") else "regroupement",
                               "categorie_cad": l["categorie_cad"], "region": l["region"]}

    def table(cumul, cles):
        return [list(c) + [_eur(cumul.get(c + (m,))) for m in ("don", "pret", "autre", "equivalent_don", "percu")]
                for c in cles]

    cles_annee = sorted(n_lignes, key=lambda c: (c[0], c[1], c[2]))
    doc = {
        "millesime": f"Déclarations {annees[0]} à {annees[-1]}",
        "source": f"{SOURCES['etat_aide_publique_developpement']['nom']} ({SOURCES['etat_aide_publique_developpement']['url']})",
        "unite": "euros courants (la source est en milliers d'euros)",
        "avertissement": "Aide publique au développement déclarée par la France au Comité d'aide au développement de "
                         "l'OCDE, activité par activité, pour tous les organismes publics (ministères, AFD, Proparco, "
                         "collectivités, organismes de recherche). " + REGLE,
        "definitions": {
            "verse": "montant versé dans l'année, avant remboursements",
            "equivalent_don": "équivalent-don : mesure de l'OCDE depuis 2018 ; un don compte pour sa totalité, un prêt "
                              "pour la part d'avantage consentie à l'emprunteur",
            "percu": "montants reçus dans l'année (remboursements de capital de prêts, récupérations sur dons)",
            "engagements": "montants engagés dans l'année",
            "famille": "don : financement « Dons » ; pret : financement « Prêt » ; autre : prises de participation, "
                       "garanties, obligations, opérations sur la dette",
        },
        "annees": annees,
        "ordre": {"cles": ["annee", "puis clé alphabétique"],
                  "regle": "Lignes par année puis par ordre alphabétique de la clé ; aucun classement par montant."},
        "par_annee": {
            "perimetre": "tous les types de flux publiés par la source, APD ou non",
            "colonnes": ["annee", "type_de_flux", "type_de_financement", "famille", "engagements_eur", "verse_eur",
                         "equivalent_don_eur", "percu_eur", "lignes"],
            "lignes": [[c[0], c[1], c[2], FAMILLES.get(c[2], "autre")]
                       + [_eur(par_annee.get(c + (m,))) for m in ("engagements", "verse", "equivalent_don", "percu")]
                       + [n_lignes[c]] for c in cles_annee]},
        "perimetre_ventilations": f"Ventilations ci-dessous : type de flux « {FLUX_APD} » seulement ; montants versés.",
        "colonnes_ventilations": ["dons_verses_eur", "prets_verses_eur", "autres_verses_eur", "equivalent_don_eur",
                                  "percu_eur"],
        "par_canal": {"colonnes": ["annee", "canal"], "lignes": table(par_canal, sorted(
            {c[:2] for c in par_canal.v}, key=lambda c: (c[0], nom_tri(c[1]))))},
        "par_agence": {"colonnes": ["annee", "agence"], "lignes": table(par_agence, sorted(
            {c[:2] for c in par_agence.v}, key=lambda c: (c[0], nom_tri(c[1]))))},
        "par_secteur": {"colonnes": ["annee", "secteur"], "lignes": table(par_secteur, sorted(
            {c[:2] for c in par_secteur.v}, key=lambda c: (c[0], nom_tri(c[1]))))},
        "pays": sorted(pays.values(), key=lambda p: (p["nom_tri"], p["code"])),
        "par_pays": {"colonnes": ["annee", "code"], "lignes": table(par_pays, sorted(
            {c[:2] for c in par_pays.v}, key=lambda c: (c[0], pays[c[1]]["nom_tri"], c[1])))},
        "limites": [
            "Les régions et les lignes « non spécifié » de la source sont gardées comme regroupements (code R suivi du "
            "code de la source) : elles ne sont pas réparties entre pays.",
            "La colonne « autres » réunit des instruments de nature différente (participations, garanties, "
            "obligations, opérations sur la dette) ; leur détail par année est dans par_annee.",
            "Les textes libres, numéros de projet et descriptions de la source ne sont pas repris.",
            "À partir des déclarations 2023, la source classe les instruments du secteur privé (prêts, participations "
            "et garanties à des entreprises) dans un type de flux à part : ils figurent dans par_annee, pas dans les "
            "ventilations par canal, organisme, secteur et pays.",
        ],
        "collecte_le": collecte["etat_aide_publique_developpement"],
    }
    resume = {"annees": annees, "usd": usd,
              "apd": {a: {m: _eur(sum(v for c, v in par_canal.v.items() if c[0] == a and c[2] == m) if any(
                  c[0] == a and c[2] == m for c in par_canal.v) else None)
                  for m in ("don", "pret", "autre", "equivalent_don", "percu")} for a in annees},
              "afd": {a: {m: _eur(par_agence.get((a, "Agence française de développement", m)))
                          for m in ("don", "pret")} for a in annees},
              "noms": {c: p["nom"] for c, p in pays.items()}}
    return doc, resume


# ------------------------------------------------------------------------------------------- AFD (standard IATI)

def lire_iati() -> tuple[list[dict], dict]:
    """Concours de l'AFD (activités IATI de niveau 2) : pays, secteur, instrument, flux, transactions par année.

    Seuls les éléments nécessaires sont lus : ni titre, ni description, ni contact, ni organisation participante.
    """
    activites, ecarte = {}, {"fichier": None, "activites": 0, "activites_absentes_ailleurs": 0}
    anciennes = set()
    genere = []
    for f in sorted(D_IATI.glob("*.xml")):
        racine = ET.parse(f).getroot()
        instantane = INSTANTANE_IATI in f.name
        if instantane:
            ecarte["fichier"], ecarte["genere_le"] = f.name, str(racine.get("generated-datetime") or "")[:10]
        else:
            genere.append(str(racine.get("generated-datetime") or "")[:10])
        for a in racine.findall("iati-activity"):
            ident = (a.findtext("iati-identifier") or "").strip()
            if instantane:
                anciennes.add(ident)
                continue
            maj = a.get("last-updated-datetime") or ""
            if ident in activites and (activites[ident]["maj"], activites[ident]["fichier"]) >= (maj, f.name):
                continue
            fin, flux = a.find("default-finance-type"), a.find("default-flow-type")
            sect = [s.get("code") for s in a.findall("sector") if s.get("vocabulary") == "1"]
            activites[ident] = {
                "maj": maj, "fichier": f.name, "niveau": a.get("hierarchy"),
                "instrument": fin.get("code") if fin is not None else None,
                "flux": flux.get("code") if flux is not None else None,
                "pays": [(c.get("code"), float(c.get("percentage") or 0)) for c in a.findall("recipient-country")],
                "secteur": sect[0] if sect else None,
                "transactions": [(t.find("transaction-type").get("code"), t.find("transaction-date").get("iso-date")[:4],
                                  float(t.findtext("value"))) for t in a.findall("transaction")],
                "devise": a.get("default-currency"),
            }
    ecarte["activites"] = len(anciennes)
    ecarte["activites_absentes_ailleurs"] = len(anciennes - set(activites))
    meta = {"ecarte": ecarte, "genere_le": max(genere) if genere else None,
            "fichiers": len(list(D_IATI.glob("*.xml"))) - (1 if ecarte["fichier"] else 0),
            "activites": len(activites)}
    return [dict(v, id=k) for k, v in sorted(activites.items())], meta


INSTRUMENTS_IATI = {"110": "don", "421": "pret"}
FLUX_IATI = {"10": "apd", "21": "autres_apports_publics"}
TYPES_IATI = {"2": "engagements", "3": "versements"}
ANNEE_MIN_AFD = 2018


def produire_afd(activites, meta, secteurs, noms, collecte) -> tuple[dict, dict]:
    par_annee, par_pays, par_secteur = Cumul(), Cumul(), Cumul()
    concours = defaultdict(set)
    ecartes = Cumul()
    n_concours, hors = 0, defaultdict(int)
    codes = {}
    for a in activites:
        if a["niveau"] != "2" or not a["transactions"]:
            continue
        ins, flux = INSTRUMENTS_IATI.get(a["instrument"]), FLUX_IATI.get(a["flux"])
        if ins is None or flux is None or a["devise"] != "EUR":
            hors[f"instrument {a['instrument']}, flux {a['flux']}, devise {a['devise']}"] += 1
            continue
        n_concours += 1
        total_pct = sum(p for _, p in a["pays"])
        parts = [(c, p / total_pct) for c, p in a["pays"] if p > 0] if total_pct > 0 else [(None, 1.0)]
        pref = (a["secteur"] or "")[:3]
        secteur = secteurs.get(pref) or (f"Autre (code CAD {pref})" if pref else "Non spécifié")
        for typ, annee, montant in a["transactions"]:
            t = TYPES_IATI.get(typ)
            if t is None:
                hors[f"transaction de type {typ}"] += 1
                continue
            an = int(annee)
            if an < ANNEE_MIN_AFD:
                ecartes.ajouter((t, ins), montant)
                continue
            par_annee.ajouter((an, flux, ins, t), montant)
            par_secteur.ajouter((an, secteur, flux, ins, t), montant)
            if t == "engagements":
                concours[(an, flux, ins)].add(a["id"])
            for c, part in parts:
                code = "NON_VENTILE" if c is None else ISO2_ISO3.get(c, c)
                codes[code] = c
                par_pays.ajouter((an, code, flux, ins, t), montant * part)
    annees = sorted({c[0] for c in par_annee.v})
    pays = []
    for code in codes:
        nom = "Non ventilé par pays" if code == "NON_VENTILE" else (noms.get(code) or NOMS_FR.get(code) or code)
        pays.append({"code": code, "nom": nom, "nom_tri": nom_tri(nom)})
    pays.sort(key=lambda p: (p["nom_tri"], p["code"]))
    tri_pays = {p["code"]: p["nom_tri"] for p in pays}
    mes = [(i, t) for i in ("don", "pret") for t in ("engagements", "versements")]

    def lignes(cumul, n):
        cles = sorted({c[:n] for c in cumul.v}, key=lambda c: (c[0], tri_pays.get(c[1], nom_tri(str(c[1]))), c[1:]))
        return [list(c) + [_eur(cumul.get(c + m)) for m in mes] for c in cles]

    doc = {
        "millesime": f"Engagements et versements {annees[0]} à {annees[-1]} (publication du {meta['genere_le']})",
        "source": f"{SOURCES['apd_afd_iati']['nom']} ({SOURCES['apd_afd_iati']['url']})",
        "unite": "euros courants",
        "avertissement": "Concours de l'Agence française de développement publiés au standard IATI, avec l'accord des "
                         "contreparties. " + REGLE + " " + FINANCEMENT_PRETS,
        "definitions": {
            "concours": "un financement de l'AFD (don ou prêt) rattaché à un projet ; un projet peut réunir plusieurs "
                        "concours",
            "don": "type de financement 110 du standard (don, subvention)",
            "pret": "type de financement 421 du standard (prêt)",
            "apd": "type de flux 10 : aide publique au développement",
            "autres_apports_publics": "type de flux 21 : autres apports du secteur public, hors APD",
            "engagements": "montant du concours, daté de la transaction d'engagement",
            "versements": "montants versés, publiés par année civile",
        },
        "annees": annees,
        "annees_partielles": [a for a in annees if a == ANNEE_MIN_AFD or str(a) == str(meta["genere_le"])[:4]],
        "colonnes_montants": ["dons_engages_eur", "prets_engages_eur", "dons_verses_eur", "prets_verses_eur"],
        "ordre": {"cles": ["annee", "nom_tri", "flux"],
                  "regle": "Lignes par année, puis par ordre alphabétique du pays ou du secteur, puis par type de "
                           "flux ; aucun classement par montant."},
        "par_annee": {"colonnes": ["annee", "flux"],
                      "lignes": [list(c) + [_eur(par_annee.get(c + (i, t))) for i, t in
                                            (("don", "engagements"), ("pret", "engagements"),
                                             ("don", "versements"), ("pret", "versements"))]
                                 for c in sorted({c[:2] for c in par_annee.v})],
                      "concours_engages": {"colonnes": ["annee", "flux", "dons", "prets"],
                                           "lignes": [[a, f, len(concours.get((a, f, "don"), ())),
                                                       len(concours.get((a, f, "pret"), ()))]
                                                      for a, f in sorted({c[:2] for c in concours})]}},
        "pays": pays,
        "par_pays": {"colonnes": ["annee", "code", "flux"],
                     "lignes": [list(c) + [_eur(par_pays.get(c + (i, t))) for i, t in
                                           (("don", "engagements"), ("pret", "engagements"),
                                            ("don", "versements"), ("pret", "versements"))]
                                for c in sorted({c[:3] for c in par_pays.v},
                                                key=lambda c: (c[0], tri_pays[c[1]], c[1], c[2]))]},
        "par_secteur": {"colonnes": ["annee", "secteur", "flux"],
                        "lignes": [list(c) + [_eur(par_secteur.get(c + (i, t))) for i, t in
                                              (("don", "engagements"), ("pret", "engagements"),
                                               ("don", "versements"), ("pret", "versements"))]
                                   for c in sorted({c[:3] for c in par_secteur.v},
                                                   key=lambda c: (c[0], nom_tri(c[1]), c[2]))]},
        "methode": "Chaque concours (activité IATI de niveau 2) porte un type de financement, un type de flux, un "
                   "secteur du CAD et ses transactions. Un concours qui vise plusieurs pays est réparti selon les "
                   "pourcentages publiés ; sans pays publié, il va dans « Non ventilé par pays ». Le secteur est le "
                   "libellé de la DG Trésor pour les trois premiers chiffres du code-objet du CAD. Quand une activité "
                   "figure dans plusieurs fichiers, la version mise à jour le plus récemment est gardée.",
        "couverture": {"fichiers": meta["fichiers"], "activites": meta["activites"], "concours_retenus": n_concours,
                       "hors_champ": [{"motif": k, "concours_ou_transactions": v} for k, v in sorted(hors.items())]},
        "ecartes": [
            {"motif": f"transactions antérieures à {ANNEE_MIN_AFD} : la publication ne couvre pas ces années en entier",
             "montants_eur": {f"{i}_{t}": _eur(ecartes.get((t, i))) for i, t in mes}},
            {"motif": "instantané d'ensemble « dans les États étrangers » publié le "
                      f"{meta['ecarte'].get('genere_le')}, remplacé depuis par les fichiers par pays : non lu pour "
                      "éviter les doubles comptes",
             "activites": meta["ecarte"]["activites"],
             "activites_absentes_des_fichiers_par_pays": meta["ecarte"]["activites_absentes_ailleurs"]},
        ],
        "limites": [
            "L'AFD publie un projet quand la contrepartie a donné son accord : la publication ne couvre pas tous ses "
            "financements.",
            "Les concours financés par des fonds délégués (Union européenne, autres bailleurs) figurent parmi les "
            "dons : ils ne viennent pas du budget de l'État.",
            "Les années signalées dans annees_partielles sont incomplètes (première année publiée, année en cours).",
            "Aucun nom de bénéficiaire ni de projet n'est repris.",
        ],
        "collecte_le": collecte["apd_afd_iati"],
    }
    resume = {"annees": annees,
              "apd": {a: {f"{i}_{t}": _eur(par_annee.get((a, "apd", i, t))) for i, t in mes} for a in annees}}
    return doc, resume


# ------------------------------------------------------------------------------------------------------- OCDE

def _lire_sdmx(chemin: Path) -> list[dict]:
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def produire_ocde(noms, collecte) -> tuple[dict, dict]:
    dac2a, dac5 = _lire_sdmx(F_DAC2A), _lire_sdmx(F_DAC5)
    cles2 = {c: k for c, k, _ in MESURES_DAC2A}
    val, recip = {}, {}
    for l in dac2a:
        if l["MEASURE"] in cles2 and l["OBS_VALUE"] not in ("", None) and l["PRICE_BASE"] == "V":
            val[(int(l["TIME_PERIOD"]), l["RECIPIENT"], cles2[l["MEASURE"]])] = round(float(l["OBS_VALUE"]), 3)
            recip[l["RECIPIENT"]] = l["Recipient"]
    est_pays = lambda c: bool(re.fullmatch(r"[A-Z]{3}", c)) and c not in ("ACP", "LDC")  # noqa: E731
    pays = []
    for c in recip:
        if est_pays(c):
            nom = noms.get(c) or NOMS_FR.get(c) or recip[c]
            pays.append({"code": c, "nom": nom, "nom_tri": nom_tri(nom), "nom_source": recip[c]})
    pays.sort(key=lambda p: (p["nom_tri"], p["code"]))
    tri = {p["code"]: p["nom_tri"] for p in pays}
    annees = sorted({c[0] for c in val})
    ordre_m = [k for _, k, _ in MESURES_DAC2A]
    lignes_pays = [[a, c] + [val.get((a, c, m)) for m in ordre_m]
                   for a, c in sorted({c[:2] for c in val if est_pays(c[1])}, key=lambda c: (c[0], tri[c[1]], c[1]))]
    ensemble = [[a] + [val.get((a, "DPGC", m)) for m in ordre_m] for a in annees]

    cles5 = {c: k for c, k, _ in MESURES_DAC5}
    v5, sect = {}, {}
    for l in dac5:
        if l["MEASURE"] in cles5 and l["OBS_VALUE"] not in ("", None) and l["PRICE_BASE"] == "V":
            v5[(int(l["TIME_PERIOD"]), l["SECTOR"], cles5[l["MEASURE"]])] = round(float(l["OBS_VALUE"]), 3)
            sect[l["SECTOR"]] = l["Sector"]
    ordre5 = [k for _, k, _ in MESURES_DAC5]
    secteurs = [{"code": c, "nom": SECTEURS_DAC5.get(c, sect[c]), "nom_source": sect[c],
                 "niveau": "total" if c in ("1000", "450") else ("groupe" if c.endswith("00") else
                                                                 ("secteur" if c.endswith("0") or c in ("331", "332", "998")
                                                                  else "sous_secteur"))}
                for c in sorted(sect, key=lambda c: (c != "1000", c))]
    lignes5 = [[a, c] + [v5.get((a, c, m)) for m in ordre5] for a, c in sorted({c[:2] for c in v5})]
    annees5 = sorted({c[0] for c in v5})
    doc = {
        "millesime": f"Versements par pays {annees[0]} à {annees[-1]} ; engagements par secteur {annees5[0]} à {annees5[-1]}",
        "source": f"{SOURCES['apd_ocde_dac2a']['nom']} ; {SOURCES['apd_ocde_dac5']['nom']} (https://sdmx.oecd.org/public/rest/)",
        "unite": "millions de dollars des États-Unis, prix courants (unité de publication de l'OCDE, non convertie)",
        "avertissement": "Statistiques du Comité d'aide au développement de l'OCDE, établies à partir des déclarations "
                         "de la France. Montants en dollars : ils ne se comparent pas directement aux fichiers en "
                         "euros. " + REGLE,
        "licence": LIC_OCDE,
        "versements_par_pays": {
            "table": "DAC2A", "annees": annees,
            "mesures": [{"cle": k, "code_ocde": c, "nom": n} for c, k, n in MESURES_DAC2A],
            "pays": pays,
            "ordre": {"cles": ["annee", "nom_tri"],
                      "regle": "Lignes par année puis par ordre alphabétique du nom du pays en français."},
            "colonnes": ["annee", "code"] + [f"{m}_musd" for m in ordre_m],
            "lignes": lignes_pays,
            "ensemble_pays_en_developpement": {"colonnes": ["annee"] + [f"{m}_musd" for m in ordre_m], "lignes": ensemble},
            "note": "Les prêts bruts et leurs remboursements sont publiés à part des dons. L'APD multilatérale imputée "
                    "est une estimation de l'OCDE : part des contributions de la France aux organisations "
                    "multilatérales attribuée à chaque pays. Régions et lignes « non spécifié » de l'OCDE ne sont pas "
                    "reprises pays par pays ; l'ensemble des pays en développement les contient.",
        },
        "engagements_par_secteur": {
            "table": "DAC5", "annees": annees5,
            "mesures": [{"cle": k, "code_ocde": c, "nom": n} for c, k, n in MESURES_DAC5],
            "secteurs": secteurs,
            "ordre": {"cles": ["annee", "code"], "regle": "Lignes par année puis par code de secteur du CAD."},
            "colonnes": ["annee", "code"] + [f"{m}_musd" for m in ordre5],
            "lignes": lignes5,
            "note": "Les secteurs sont emboîtés (total, groupe, secteur, sous-secteur) : les lignes d'un niveau ne "
                    "s'ajoutent pas à celles d'un autre. L'OCDE publie les engagements d'APD dons et prêts réunis, et "
                    "à part la ligne « dont dons » ; la part des prêts n'est pas publiée dans cette table.",
        },
        "limites": [
            "Une valeur absente de la publication de l'OCDE est null, jamais 0.",
            "Les noms de pays sont ceux de la DG Trésor quand le code existe dans son jeu ; sinon le nom publié par "
            "l'OCDE (nom_source) est gardé.",
        ],
        "collecte_le": collecte["apd_ocde_dac2a"],
    }
    return doc, {"annees": annees, "ensemble": {a: {m: val.get((a, "DPGC", m)) for m in ordre_m} for a in annees}}


# ------------------------------------------------------------------------------------------- Expertise France

def produire_expertise_france(collecte) -> dict:
    """Agrégats par pays, bailleur, année et type d'acte. Les colonnes « attributaires », « objet du contrat »,
    « intitulé du projet » et « numéro du contrat » ne sont jamais lues."""
    cumul, nb = Cumul(), defaultdict(int)
    exclus = {"contrats": 0, "montant": 0.0}
    inconnus = defaultdict(int)
    with F_EF.open(encoding="utf-8-sig", newline="") as f:
        for l in csv.DictReader(f, delimiter=";"):
            acte = (l.get("type_d_acte") or "").strip()
            try:
                montant = float(l.get("montant_initial_maximal_eurht") or "")
            except ValueError:
                montant = None
            if acte == ACTE_EXCLU_EF:
                exclus["contrats"] += 1
                exclus["montant"] += montant or 0.0
                continue
            if acte not in ACTES_EF:
                inconnus[acte or "type d'acte non renseigné"] += 1
                continue
            date = (l.get("date_d_entree_en_vigueur_du_contrat") or "").strip()
            annee = int(date[:4]) if re.match(r"\d{4}-", date) else None
            lieu = (l.get("lieu_d_execution_pays_beneficiaire_s_du_projet") or "").strip()
            pays = "Non renseigné" if not lieu else ("Plusieurs pays" if "," in lieu else lieu)
            bailleur = (l.get("bailleur") or "").strip() or "Non renseigné"
            cle = (annee, pays, bailleur, ACTES_EF[acte])
            nb[cle] += 1
            cumul.ajouter(cle, montant)
    annees = sorted({c[0] for c in nb if c[0] is not None})
    cles = sorted(nb, key=lambda c: (c[0] is None, c[0] or 0, nom_tri(c[1]), nom_tri(c[2]), c[3]))
    par_bailleur, par_pays = Cumul(), Cumul()
    nbb, nbp = defaultdict(int), defaultdict(int)
    for c in nb:
        fam = "plafonds_accords_cadres" if c[3] == "accord_cadre" else "contrats"
        par_bailleur.ajouter((c[2], fam), cumul.get(c))
        par_pays.ajouter((c[1], fam), cumul.get(c))
        nbb[(c[2], fam)] += nb[c]
        nbp[(c[1], fam)] += nb[c]

    def resume(cumul2, n2):
        return [[k, n2.get((k, "contrats"), 0), _eur(cumul2.get((k, "contrats"))),
                 n2.get((k, "plafonds_accords_cadres"), 0), _eur(cumul2.get((k, "plafonds_accords_cadres")))]
                for k in sorted({c[0] for c in n2}, key=nom_tri)]

    return {
        "millesime": f"Contrats entrés en vigueur de {annees[0]} à {annees[-1]}",
        "source": f"{SOURCES['apd_expertise_france_contrats']['nom']} ({SOURCES['apd_expertise_france_contrats']['url']})",
        "unite": "euros hors taxes ; montant initial maximal de chaque contrat",
        "avertissement": "Contrats de plus de 15 000 euros conclus par Expertise France pour des projets de "
                         "coopération technique, agrégés par pays et par bailleur. Le montant publié est un montant "
                         "initial maximal, pas une dépense constatée. Un accord-cadre fixe un plafond : il est compté "
                         "à part et ne s'ajoute pas aux marchés. La plupart des projets sont financés par des "
                         "bailleurs autres que l'État (Union européenne, AFD). " + REGLE,
        "licence": LIC_AFD_NP,
        "definitions": {
            "marche": "marché d'achat (services, fournitures, travaux, prestations intellectuelles)",
            "marche_subsequent": "marché passé en application d'un accord-cadre",
            "subvention": "subvention versée à un partenaire du projet",
            "accord_cadre": "accord-cadre : plafond de commandes possibles, pas un montant commandé ni dépensé",
            "bailleur": "organisme qui finance le projet, tel que publié par Expertise France",
        },
        "regle_personnes": "Aucun attributaire n'est nommé : la source mêle des sociétés, des associations et des "
                           "personnes physiques sans identifiant qui permette de les distinguer. Les contrats d'experts "
                           "individuels, conclus avec des personnes physiques, sont exclus de toutes les ventilations.",
        "annees": annees,
        "ordre": {"cles": ["annee", "pays", "bailleur", "type"],
                  "regle": "Lignes par année, puis par ordre alphabétique du pays, du bailleur et du type d'acte ; "
                           "aucun classement par montant."},
        "colonnes": ["annee", "pays", "bailleur", "type", "contrats", "montant_initial_maximal_eur"],
        "lignes": [list(c) + [nb[c], _eur(cumul.get(c))] for c in cles],
        "par_bailleur": {"colonnes": ["bailleur", "contrats", "montant_initial_maximal_eur", "accords_cadres",
                                      "plafonds_accords_cadres_eur"], "lignes": resume(par_bailleur, nbb)},
        "par_pays": {"colonnes": ["pays", "contrats", "montant_initial_maximal_eur", "accords_cadres",
                                  "plafonds_accords_cadres_eur"], "lignes": resume(par_pays, nbp)},
        "ecartes": [
            {"motif": "contrats d'experts individuels : personnes physiques, exclus des ventilations et donnés ici en "
                      "un seul total", "contrats": exclus["contrats"],
             "montant_initial_maximal_eur": _eur(exclus["montant"])},
        ] + [{"motif": f"type d'acte hors nomenclature : {k}", "contrats": v} for k, v in sorted(inconnus.items())],
        "limites": [
            "Un contrat exécuté dans plusieurs pays est classé « Plusieurs pays » : son montant n'est pas réparti.",
            "Les noms de pays sont ceux de la source ; « France » désigne des contrats exécutés en France.",
            "Les contrats de 15 000 euros ou moins ne sont pas publiés par la source.",
        ],
        "collecte_le": collecte["apd_expertise_france_contrats"],
    }


# ------------------------------------------------------------------------------------------------------ Proparco

def _instrument_proparco(t: str) -> str:
    s = nom_tri(t or "")
    if s.startswith("pret"):
        return "pret"
    if s.startswith(("prise de participation", "fds propres", "autres titres")):
        return "participation"
    if s.startswith(("garantie", "gar ")):
        return "garantie"
    if s.startswith("subvention"):
        return "don"
    if s.startswith("accompagnement"):
        return "accompagnement_technique"
    if s.startswith("obligation"):
        return "obligation"
    return "non_renseigne"


def produire_proparco(collecte) -> dict:
    """Agrégats par année de signature, pays et instrument. Noms de clients, titres et descriptions jamais lus."""
    cumul, nb = Cumul(), defaultdict(int)
    sans_date = {"financements": 0, "montant": 0.0}
    graphies = defaultdict(lambda: defaultdict(int))  # « MAROC » et « Maroc » : une seule ligne, graphie la plus fréquente
    with F_PROPARCO.open(encoding="utf-8-sig", newline="") as f:
        for l in csv.DictReader(f, delimiter=";"):
            try:
                montant = float(l.get("montant_du_financement_en_euro") or "")
            except ValueError:
                montant = None
            date = (l.get("date_de_signature") or "").strip()
            if not re.match(r"\d{4}-", date):
                sans_date["financements"] += 1
                sans_date["montant"] += montant or 0.0
                continue
            lieu = re.sub(r"\s+", " ", (l.get("pays_de_realisation") or "").strip())
            pays = "Non renseigné" if not lieu else ("Plusieurs pays" if re.search(r"[,;/]|multi", lieu, re.I) else lieu)
            cle_pays = re.sub(r"[^a-z]+", " ", nom_tri(pays)).strip()
            graphies[cle_pays][pays] += 1
            cle = (int(date[:4]), cle_pays, _instrument_proparco(l.get("type_de_financement_1")))
            nb[cle] += 1
            cumul.ajouter(cle, montant)
    affiche = {k: sorted(g.items(), key=lambda kv: (kv[0].isupper(), -kv[1], kv[0]))[0][0] for k, g in graphies.items()}
    affiche = {k: (v.title() if v.isupper() and len(v) > 4 else v) for k, v in affiche.items()}
    annees = sorted({c[0] for c in nb})
    cles = sorted(nb, key=lambda c: (c[0], c[1], c[2]))
    pa, npa = Cumul(), defaultdict(int)
    for c in nb:
        pa.ajouter((c[0], c[2]), cumul.get(c))
        npa[(c[0], c[2])] += nb[c]
    return {
        "millesime": f"Financements signés de {annees[0]} à {annees[-1]}",
        "source": f"{SOURCES['apd_proparco']['nom']} ({SOURCES['apd_proparco']['url']})",
        "unite": "euros ; montant du financement signé",
        "avertissement": "Financements signés par Proparco, filiale du groupe AFD pour le secteur privé, agrégés par "
                         "année, pays et instrument. Proparco intervient surtout par des prêts, des prises de "
                         "participation et des garanties, sur ses fonds propres et des ressources empruntées, et non "
                         "sur des crédits budgétaires. " + REGLE,
        "licence": LIC_AFD_NP,
        "definitions": {
            "pret": "prêt", "participation": "prise de participation, fonds propres, autres titres",
            "garantie": "garantie : engagement de couvrir un risque, pas un versement",
            "don": "subvention", "accompagnement_technique": "accompagnement technique", "obligation": "obligation",
            "non_renseigne": "type de financement absent ou hors nomenclature dans la source",
        },
        "regle_personnes": "Aucun client n'est nommé dans ce fichier : seuls des agrégats par pays sont publiés.",
        "annees": annees,
        "ordre": {"cles": ["annee", "pays", "instrument"],
                  "regle": "Lignes par année, puis par ordre alphabétique du pays et de l'instrument ; aucun "
                           "classement par montant."},
        "par_annee": {"colonnes": ["annee", "instrument", "financements", "montant_eur"],
                      "lignes": [[a, i, npa[(a, i)], _eur(pa.get((a, i)))] for a, i in sorted(npa)]},
        "colonnes": ["annee", "pays", "instrument", "financements", "montant_eur"],
        "lignes": [[c[0], affiche[c[1]], c[2], nb[c], _eur(cumul.get(c))] for c in cles],
        "ecartes": [{"motif": "date de signature absente : financement non rattaché à une année",
                     "financements": sans_date["financements"], "montant_eur": _eur(sans_date["montant"])}],
        "limites": [
            "L'instrument est déduit du premier type de financement publié ; un second type éventuel n'est pas repris.",
            "Un financement réalisé dans plusieurs pays est classé « Plusieurs pays » : son montant n'est pas réparti.",
            "Les instruments ne s'additionnent pas : un prêt, une participation et une garantie n'ont pas la même "
            "nature.",
            "Les noms de pays sont ceux de la source ; seules la casse et l'accentuation sont harmonisées (deux "
            "graphies différentes d'un même pays restent deux lignes).",
        ],
        "collecte_le": collecte["apd_proparco"],
    }


# --------------------------------------------------------------------------------------- crédits budgétaires, index

def credits_budgetaires() -> dict:
    """Mission « Aide publique au développement » de l'arbre de l'État (déjà produit par pipeline/transform.py)."""
    vues = []
    for dossier in ("arbre", "arbre_lfi2025"):
        f = SITE / dossier / "racine.json"
        if not f.exists():
            continue
        racine = json.loads(f.read_text(encoding="utf-8"))
        for poste in racine.get("enfants", []):
            for mission in poste.get("enfants", []):
                if nom_tri(mission.get("nom", "")) == "aide publique au developpement":
                    vues.append({
                        "vue": dossier, "millesime": racine.get("millesime"), "fichier_racine": f"{dossier}/racine.json",
                        "mission": {"id": mission["id"], "nom": mission["nom"], "md": mission.get("md")},
                        "programmes": [{"numero": p["id"].rsplit("/", 1)[-1], "nom": p["nom"], "md": p.get("md"),
                                        "fichier": p.get("fichier")}
                                       for p in sorted(mission.get("enfants", []), key=lambda p: p["id"])]})
    return {
        "unite": "milliards d'euros, crédits de paiement",
        "source": "site/data/arbre (budget de l'État, pipeline/transform.py)",
        "vues": vues,
        "lecture": "La mission budgétaire ne contient qu'une partie de l'aide publique au développement déclarée : la "
                   "déclaration à l'OCDE compte aussi des dépenses d'autres missions, des collectivités et les prêts "
                   "de l'AFD. Les deux montants ne se comparent pas terme à terme et ne s'additionnent pas.",
    }


def _ecart(annee, comparaison, unite, source, montant, autre_source, autre_montant, lecture) -> dict | None:
    if montant is None or autre_montant is None:
        return None
    e = montant - autre_montant
    return {"annee": annee, "comparaison": comparaison, "unite": unite, "source": source, "montant": montant,
            "autre_source": autre_source, "autre_montant": autre_montant, "ecart": round(e, 3),
            "ecart_pct": round(e / autre_montant * 100, 1) if autre_montant else None, "lecture": lecture}


def produire(sortie: Path = SORTIE) -> None:
    collecte = _collectes()
    lignes = lire_etat()
    declaree, r_dec = produire_declaree(lignes, collecte)
    activites, meta = lire_iati()
    afd, r_afd = produire_afd(activites, meta, secteurs_cad(lignes), r_dec["noms"], collecte)
    ocde, r_ocde = produire_ocde(r_dec["noms"], collecte)
    ef = produire_expertise_france(collecte)
    proparco = produire_proparco(collecte)

    ecarts = []
    lect_afd = ("Deux publications de périmètres différents : la déclaration à l'OCDE couvre toute l'APD de l'AFD ; "
                "la publication IATI couvre les concours dont la contrepartie a accepté la publication. L'écart est "
                "publié tel quel.")
    lect_ocde = ("Même déclaration d'origine ; l'OCDE publie en dollars et ajoute ses propres traitements. Montant de "
                 "la DG Trésor : versements bilatéraux d'APD en dollars de son jeu. L'écart est publié tel quel.")
    for a in r_dec["annees"]:
        for fam, lib, cle in (("don", "dons", "don_versements"), ("pret", "prêts", "pret_versements")):
            if a in r_afd["apd"] and a not in afd["annees_partielles"]:
                ecarts.append(_ecart(a, f"AFD, {lib} d'APD versés", "euros", "afd_iati", r_afd["apd"][a][cle],
                                     "apd_declaree (agence AFD)", r_dec["afd"][a][fam], lect_afd))
        if a in r_ocde["ensemble"]:
            for fam, lib, cle in (("don", "dons", "dons"), ("pret", "prêts bruts", "prets_bruts")):
                u = r_dec["usd"].get((a, fam))
                ecarts.append(_ecart(a, f"APD bilatérale, {lib} versés", "millions de dollars courants", "ocde_dac2a",
                                     r_ocde["ensemble"][a][cle], "apd_declaree (bilatéral)",
                                     None if u is None else round(u, 3), lect_ocde))
    ecarts = [e for e in ecarts if e]

    budget = credits_budgetaires()
    index = {
        "millesime": f"APD déclarée {r_dec['annees'][0]}-{r_dec['annees'][-1]} ; AFD {r_afd['annees'][0]}-{r_afd['annees'][-1]} ; "
                     f"OCDE {r_ocde['annees'][0]}-{r_ocde['annees'][-1]} ; Expertise France {ef['annees'][0]}-{ef['annees'][-1]} ; "
                     f"Proparco {proparco['annees'][0]}-{proparco['annees'][-1]}",
        "source": "DG Trésor (data.economie.gouv.fr), AFD (data.gouv.fr, opendata.afd.fr), OCDE (sdmx.oecd.org), "
                  "budget de l'État (site/data/arbre)",
        "unite": "euros, sauf OCDE (millions de dollars courants) et crédits budgétaires (milliards d'euros)",
        "avertissement": REGLE,
        "regle": REGLE,
        "financement_des_prets": {"texte": FINANCEMENT_PRETS, "producteur": "Agence française de développement",
                                  "perimetre": "prêts de l'AFD ; les programmes 110, 209 et 365 sont ceux de la "
                                               "mission « Aide publique au développement »",
                                  "methode": "description du modèle de financement publiée par l'AFD ; les crédits des "
                                             "programmes cités sont dans credits_budgetaires"},
        "grandeurs": [
            {"id": "credits_budgetaires", "nom": "Crédits budgétaires de la mission « Aide publique au développement »",
             "producteur": "Direction du budget", "unite": "milliards d'euros",
             "perimetre": "budget général de l'État, quatre programmes de la mission",
             "methode": "comptabilité budgétaire, crédits de paiement", "financement": "impôts et emprunts de l'État",
             "fichier": "arbre/racine.json"},
            {"id": "apd_declaree", "nom": "Aide publique au développement déclarée à l'OCDE",
             "producteur": SOURCES["etat_aide_publique_developpement"]["producteur"], "unite": "euros",
             "perimetre": "tous les organismes publics français, bilatéral et multilatéral",
             "methode": "déclaration annuelle au CAD, activité par activité ; versements et équivalent-don",
             "financement": "crédits budgétaires de plusieurs missions, ressources de l'AFD et de Proparco, "
                            "collectivités",
             "fichier": "aide_developpement/apd_declaree.json"},
            {"id": "afd", "nom": "Concours de l'AFD : dons et prêts",
             "producteur": SOURCES["apd_afd_iati"]["producteur"], "unite": "euros",
             "perimetre": "concours publiés avec l'accord des contreparties, APD et autres apports publics",
             "methode": "standard IATI : engagements et versements par concours",
             "financement": "dons : crédits budgétaires et fonds délégués ; prêts : emprunts de l'AFD sur les marchés, "
                            "bonifiés pour partie par l'État",
             "fichier": "aide_developpement/afd.json"},
            {"id": "proparco", "nom": "Financements signés par Proparco",
             "producteur": SOURCES["apd_proparco"]["producteur"], "unite": "euros",
             "perimetre": "financements au secteur privé publiés par Proparco",
             "methode": "montant signé par financement, agrégé par année, pays et instrument",
             "financement": "fonds propres et ressources empruntées du groupe AFD",
             "fichier": "aide_developpement/proparco.json"},
            {"id": "expertise_france", "nom": "Contrats d'Expertise France de plus de 15 000 euros",
             "producteur": SOURCES["apd_expertise_france_contrats"]["producteur"], "unite": "euros hors taxes",
             "perimetre": "marchés, subventions et accords-cadres ; experts individuels exclus",
             "methode": "montant initial maximal par contrat ; accords-cadres comptés à part comme plafonds",
             "financement": "bailleurs des projets : Union européenne, AFD, ministères, autres",
             "fichier": "aide_developpement/expertise_france.json"},
            {"id": "ocde", "nom": "Statistiques du CAD de l'OCDE pour la France",
             "producteur": SOURCES["apd_ocde_dac2a"]["producteur"], "unite": "millions de dollars courants",
             "perimetre": "APD de la France par pays (versements) et par secteur (engagements bilatéraux)",
             "methode": "tables DAC2A et DAC5, à partir des déclarations de la France",
             "financement": "sans objet : même aide que la grandeur « apd_declaree », vue par l'OCDE",
             "fichier": "aide_developpement/ocde.json"},
        ],
        "credits_budgetaires": budget,
        "totaux": {
            "note": "Une ligne par grandeur et par année ; dons et prêts en colonnes séparées, sans total commun.",
            "apd_declaree": {
                "perimetre": f"type de flux « {FLUX_APD} », montants versés, tous organismes",
                "colonnes": ["annee", "dons_verses_eur", "prets_verses_eur", "autres_verses_eur", "equivalent_don_eur",
                             "percu_eur"],
                "lignes": [[a] + [r_dec["apd"][a][m] for m in ("don", "pret", "autre", "equivalent_don", "percu")]
                           for a in r_dec["annees"]]},
            "afd": {
                "perimetre": "concours de l'AFD de type APD publiés au standard IATI",
                "annees_partielles": afd["annees_partielles"],
                "colonnes": ["annee", "dons_engages_eur", "prets_engages_eur", "dons_verses_eur", "prets_verses_eur"],
                "lignes": [[a] + [r_afd["apd"][a][m] for m in ("don_engagements", "pret_engagements",
                                                                "don_versements", "pret_versements")]
                           for a in r_afd["annees"]]},
            "ocde": {
                "perimetre": "ensemble des pays en développement, table DAC2A",
                "colonnes": ["annee"] + [f"{k}_musd" for _, k, _ in MESURES_DAC2A],
                "lignes": [[a] + [r_ocde["ensemble"][a][k] for _, k, _ in MESURES_DAC2A] for a in r_ocde["annees"]]},
        },
        "ecarts": ecarts,
        "ecarts_note": "Écarts entre sources pour un même objet : publiés, jamais corrigés ni arbitrés.",
        "fichiers": [
            {"fichier": "aide_developpement/apd_declaree.json", "contenu": "APD déclarée : par année, instrument, "
             "canal, organisme, secteur et pays"},
            {"fichier": "aide_developpement/afd.json", "contenu": "AFD : dons et prêts, engagements et versements, par "
             "année, pays et secteur"},
            {"fichier": "aide_developpement/ocde.json", "contenu": "OCDE : versements par pays, engagements par secteur"},
            {"fichier": "aide_developpement/expertise_france.json", "contenu": "Expertise France : contrats par pays, "
             "bailleur, année et type d'acte"},
            {"fichier": "aide_developpement/proparco.json", "contenu": "Proparco : financements signés par année, pays "
             "et instrument"},
        ],
        "sources": [dict(id=sid, **s, collecte_le=collecte[sid]) for sid, s in SOURCES.items()],
        "sources_inaccessibles": [
            {"source": "OCDE, page des conditions d'utilisation (https://www.oecd.org/en/about/terms-conditions.html)",
             "constat": "refus 403 à la lecture par script le 17/11/2026 ; non contourné. La licence indiquée vient du "
                        "communiqué de l'OCDE du 4 juillet 2024 sur le passage en accès ouvert."},
        ],
        "limites": [
            "Les fichiers n'ont pas les mêmes années : chaque fichier donne les siennes.",
            "Les noms de pays viennent de sources différentes (DG Trésor, AFD, OCDE, Expertise France, Proparco) ; "
            "seuls les fichiers APD déclarée, AFD et OCDE partagent des codes de pays à trois lettres.",
            "Proparco et l'AFD figurent aussi, pour leur part d'APD, dans l'APD déclarée : les fichiers se recouvrent.",
        ],
        "collecte_le": date_sources("aide_developpement"),
        "recherche_publique": RECHERCHE_PUBLIQUE,
    }
    for nom, doc in (("apd_declaree.json", declaree), ("afd.json", afd), ("ocde.json", ocde),
                     ("expertise_france.json", ef), ("proparco.json", proparco), ("index.json", index)):
        _ecrire(sortie / nom, doc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("produire")
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = ap.parse_args(argv)
    produire(a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
