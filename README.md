# Où vont mes impôts

Site citoyen gratuit : à partir de ton salaire net, voir où va ton argent (État, Sécurité sociale, collectivités), et pour chaque euro du budget de l'État, ce qui a été prévu, dépensé, à qui et avec quels résultats. Uniquement des données publiques ouvertes, chaque montant renvoie à sa source.

## Architecture

```
collecte/ ──> data/lake (entrepôt brut, OVH)  ──┐
fetch.py  ──> data/raw (versionné)  ────────────┼──> pipeline/ ──> site/data/*.json ──> web/ (site)
                                                │                       │
                                                │       docs/valider_contrat.py (JSON Schema)
```

| Étape | Dossier | Rôle |
|---|---|---|
| Collecte | `collecte/`, `deploy/` | collecte large et brute (6 000 sources), tracée dans `data/lake/manifest.json` ; tourne chaque semaine sur un VPS et range tout dans OVH Object Storage (`docs/STOCKAGE.md`) |
| Entrepôt | `data/lake/` (non versionné), `data/raw/` (versionné) | `data/raw` : petites sources téléchargées par `pipeline/fetch.py` à chaque passage ; `data/lake` : tout le reste |
| Pipeline | `pipeline/` | transforme en fichiers compacts pour le site, avec `millesime` et `source` dans chaque fichier |
| Données du site | `site/data/` (versionné) | format fixé par le contrat d'interface `docs/contrat_interface.md` et ses schémas `docs/schemas/` |
| Site | `web/` | Vite + TypeScript ; calcul personnel dans le navigateur (`modele-social`, `publicodes`) |

Modules du pipeline, dans l'ordre (chacun lit les sorties des précédents) :

| Module | Entrées | Sorties |
|---|---|---|
| `fetch.py`, `check_schema.py`, `transform.py` | `data/raw` (réseau) | arbres État, sankey, programmes, Eurostat, communes, `meta.json` |
| `beneficiaires.py` | `data/lake` + API Recherche d'entreprises | `nature/`, `effectifs/`, `beneficiaires/` |
| `realisations.py` | `data/lake` + ccomptes.fr | `realisations/` |
| `vie_politique.py` | `data/lake` (CNCCFP, JO, programme 232) | `vie_politique/` |
| `decisions.py` | `data/lake` (AN, Sénat, JORF, PLRG) | `decisions/` (en cours) |
| `tracabilite.py` | `site/data` + `data/lake` | `tracabilite/` (en cours) |
| `local.py` | `data/lake` + API géo et OFGL | `local/` (en cours) |

## Commandes

```bash
pip install -r requirements.txt

# budget, Eurostat, communes (réseau, quelques minutes)
python pipeline/fetch.py && python pipeline/check_schema.py && python pipeline/transform.py

# modules de précision (entrepôt brut data/lake requis)
python pipeline/beneficiaires.py tout
python pipeline/realisations.py produire
python pipeline/vie_politique.py produire

# contrôles
frictionless validate datapackage.json
python docs/valider_contrat.py --quiet
pytest -q

# site
cd web && npm ci && npm run dev
```

Changement de schéma attendu à la source : `python pipeline/check_schema.py --accept`. Nouvelle mission au budget : la rattacher dans `pipeline/grands_postes.json` (le pipeline échoue tant qu'elle ne l'est pas). Collecte de l'entrepôt : `python collecte/collecte.py --help` et `docs/STOCKAGE.md`.

**Mise à jour automatique** (`.github/workflows/data.yml`, chaque lundi) : fetch, contrôle de schéma, transform, modules de précision (sautés avec un avis sur le runner GitHub, qui n'a pas `data/lake` : leurs fichiers publiés restent tels quels), Frictionless, contrat, tests, puis commit **seulement si une donnée a changé** (l'horodatage `genere_le` de `meta.json` seul ne déclenche rien). En cas d'échec, une issue `pipeline-donnees` est ouverte ou commentée.

## Données couvertes

| Donnée | Millésime | Source |
|---|---|---|
| Budget de l'État par grand poste, mission, programme, action | exécution 2024 (vue par défaut), LFI 2025 | data.economie.gouv.fr, budget vert PLF 2026, PLRG 2024 |
| Répartition par nature (vue séparée) | PLF 2025 | data.economie.gouv.fr |
| Nature réelle, effectifs par programme | exécution 2024 ; ETPT LFI 2023 | PLRG 2024, jaune ETPT |
| Bénéficiaires nommés (personnes morales) | associations 2023, France 2030 (2021-2025), marchés de l'État 2024 | jaunes PLF 2025, France 2030, DECP |
| Prévu / dépensé, indicateurs de performance, évaluations | exécution 2010-2025 (trous 2015-2017, 2021), performance 2012-2025 | PLR, RAP, PAP, Cour des comptes |
| Vie politique : programme 232, aide aux partis, comptes de campagne | 2012 à 2025 | CNCCFP, Journal officiel |
| Dépenses publiques par fonction, par administration, recettes par impôt | 2005 à 2025 | Eurostat `gov_10a_exp`, `gov_10a_main`, `gov_10a_taxag` |
| Solde public, part empruntée | État 2024-2025 ; APU 2015-2025 | DGFiP, Eurostat |
| Taux de taxe foncière et TEOM par commune | exercice 2025 | DGFiP (REI) |

Le détail (champs, unités, contrôles) est dans `docs/contrat_interface.md`.

## Règles

- **Personnes physiques** : seules les personnes morales sont nommées (catégorie juridique 2xxx à 9xxx). Entrepreneurs individuels, SIREN absents ou invalides : agrégés, jamais nommés. Les sources qui en contiennent vont dans `data/lake/_restreint/` et le bucket privé, jamais dans `site/data`.
- **Candidats nommés** : seule exception, les candidats des comptes de campagne publiés par la CNCCFP ou au Journal officiel, avec une liste blanche de champs (ni adresse, ni date de naissance, ni donateur).
- **Traçabilité** : chaque fichier porte `millesime` et `source` ; un montant écarté (remboursements et dégrèvements, hors périmètre, aberrant) est publié avec sa raison dans `meta.json` ou le fichier concerné, jamais supprimé en silence. Comptabilité budgétaire (État) et nationale (APU) ne sont jamais mélangées.
- **Contrat** : tout nouveau fichier de `site/data` a son schéma dans `docs/schemas/` et sa section dans `docs/contrat_interface.md` ; `pytest` échoue sinon.
- **Calcul personnel** : dans le navigateur uniquement ; OpenFisca sert seulement de référence dans les tests (`tests/cas_types/`).

## Licences

Code : MIT (`LICENSE`). Données : Licence Ouverte 2.0 (Etalab) pour les sources françaises, conditions Eurostat (réutilisation libre avec mention de la source). Contribuer : `CONTRIBUTING.md` ; code de conduite : `CODE_OF_CONDUCT.md`.
