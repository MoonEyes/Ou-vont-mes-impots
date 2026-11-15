# Où vont mes impôts

Site citoyen gratuit : à partir de ton salaire net, voir où va ton argent (État, Sécurité sociale), à partir des données publiques ouvertes.

Ce dépôt contient pour l'instant le **pipeline de données**.

## Récupération des données

Méthode « git scraping » : un workflow planifié télécharge les sources, vérifie leur schéma, transforme, valide, puis committe uniquement s'il y a un changement. L'historique git sert de versionnage des données.

```
fetch.py  ->  check_schema.py  ->  transform.py  ->  frictionless validate  ->  pytest  ->  commit si diff
```

| Source | Contenu | Accès |
|---|---|---|
| data.economie.gouv.fr `plf25-depenses-...` | Budget de l'État par mission et programme | API Opendatasoft v2.1, export JSON |
| data.economie.gouv.fr `fiscalite-locale-des-particuliers` | Taux de taxe foncière et TEOM par commune (dernier exercice) | idem |
| Eurostat `gov_10a_exp` | Dépenses publiques par fonction (COFOG) | API JSON-stat |
| Eurostat `gov_10dd_edpt1` | Solde public (déficit) | API JSON-stat |

## Commandes

```bash
pip install -r requirements.txt
python pipeline/fetch.py            # télécharge data/raw/
python pipeline/check_schema.py     # échoue si la source a changé de schéma
python pipeline/transform.py        # produit site/data/
frictionless validate datapackage.json
pytest -q
```

Changement de schéma attendu : `python pipeline/check_schema.py --accept`.
Nouvelle mission au budget : l'ajouter dans `pipeline/grands_postes.json` (le pipeline échoue tant qu'elle n'est pas rattachée).

## Entrepôt brut (collecte/)

Collecte large et brute de tout ce qui touche à l'argent public, tracée dans `data/lake/manifest.json` (non versionné).

```bash
python collecte/decouverte.py                         # recense les jeux des portails (collecte/decouvertes.json)
python collecte/collecte.py --domaine etat            # catalogue manuel (collecte/catalogue.json), par domaine
python collecte/collecte.py --decouvertes --score-min 4 --portail economie
python collecte/collecte.py --lourd                   # sources > 100 Mo (garde --reserve-go libres)
python collecte/rapport.py                            # collecte/RAPPORT_COLLECTE.md
pytest -q collecte/tests                              # tests sans réseau
```

Une source déjà collectée et inchangée en amont n'est pas retéléchargée. Les données de personnes physiques (publiées en open data officiel) vont dans `data/lake/_restreint/` et ne doivent pas être affichées nominativement.

## Choix de méthode

- Les remboursements et dégrèvements d'impôts (147 Md€) sont exclus : ce sont des restitutions, pas des dépenses.
- Montants en crédits de paiement du projet de loi de finances (PLF 2025). Passage à la LFI votée ou à la dépense exécutée prévu (jeu budget vert 2026).
- En cas d'échec, le workflow ouvre (ou commente) une issue `pipeline-donnees`.

## Licences

Code : MIT. Données : Licence Ouverte 2.0 (Etalab) et conditions Eurostat (réutilisation libre avec mention de la source).
