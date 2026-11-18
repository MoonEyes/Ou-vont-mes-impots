# Rapport renfort-donnees (vague 3)

14 missions sur 14 terminées, branches poussées (hash distant = hash local pour chacune).

Statut GitHub Actions : « failure » partout, pour la même raison sur chaque branche : seul tests/test_datapackage.py échoue (nouveaux fichiers absents de docs/datapackage, que REGLES.md interdit de régénérer). Le job Site est vert partout. À faire à l'intégration : python pipeline/datapackage.py.

| Mission | Branche | Hash | Résumé | Actions |
|---|---|---|---|---|
| q17_agriculture | agent/agriculture | a73fd4d | PAC par département (série 2005-2009, Telepac en 503), FEADER 2014-2022 par ancienne région, FEAGA 2024, programme 149. | failure (datapackage seul) |
| q18_transports | agent/transports | a43f38a | AFITF, SNCF Réseau, TER et Intercités, versement mobilité 2024 (12,2 Md€), programme 203. | failure (datapackage seul) |
| q19_energie-climat | agent/energie-climat | b3722c0 | Charges de service public de l'énergie (CRE), boucliers tarifaires 2022-2024, chèque énergie au budget. | failure (datapackage seul) |
| q20_culture-medias | agent/culture-medias | fa3a77f | Missions Culture et Médias, audiovisuel public 2023-2026, aides à la presse 2012-2025, CNC 2025. | failure (datapackage seul) |
| q21_sport | agent/sport | 16d5b44 | Programmes 219 et 350, Agence nationale du sport, fédérations, CNDS 2015, dépenses publiques JOP 2024 (Cour des comptes). | failure (datapackage seul) |
| q22_emploi | agent/emploi | 324c1d2 | Comptes Unédic 2025, France Travail, activité partielle (Urssaf, Unédic), aides à l'embauche. | failure (datapackage seul) |
| q23_petite-enfance | agent/petite-enfance | 2e7fcc7 | Complément mode de garde, action sociale CAF, places d'accueil par département 2017-2025. | failure (datapackage seul) |
| q24_eau-environnement | agent/eau-environnement | 3ae1371 | Redevances et aides des agences de l'eau, aides ADEME 2021-2026, Fonds vert 2023-2025. | failure (datapackage seul) |
| q25_securite-interieure | agent/securite-interieure | 4834bfe | Police, gendarmerie, sécurité civile, sécurité routière, compte des amendes, emplois. | failure (datapackage seul) |
| q26_fiscalite-locale-series | agent/fiscalite-locale-series | b99812a | Taux et produits des impôts locaux par commune 2010-2025 (REI DGFiP), 74 Mo répartis par département. | failure (datapackage seul) |
| q27_pouvoirs-publics | agent/pouvoirs-publics | 1389ebf | Dotations de la mission Pouvoirs publics 2010-2027, budgets de l'Assemblée, indemnités par fonction. | failure (datapackage seul) |
| q28_assurance-maladie-territoires | agent/assurance-maladie-territoires | 2a10909 | ONDAM 2024-2027, honoraires et prescriptions par département 2010-2025, établissements privés. | failure (datapackage seul) |
| q29_immobilier-etat | agent/immobilier-etat | cdfb189 | Parc immobilier de l'État, loyers, cessions, compte d'affectation spéciale. | failure (datapackage seul) |
| q30_douanes-accises | agent/douanes-accises | e6d9cb3 | Accises et droits de douane (Insee, OCDE), affectation par bénéficiaire, perception par la douane 2021-2025. | failure (datapackage seul) |

## Points pour l'intégration

- Toutes les branches ajoutent une section numérotée 2.41 au contrat : collisions certaines à la fusion, à renuméroter.
- Régénérer docs/datapackage après fusion.
- Arbitrages signalés par les agents (détails dans leurs index.json et sections du contrat) : série PAC arrêtée en 2009 ; taux 2023-2025 de fiscalite-locale-series mis à null au profit de local/taux (58 225 écarts net/voté) ; traitement présidentiel calculé dans pouvoirs-publics ; sélection par le mot « fédération » dans sport ; filtre de noms de presse avec faux positifs possibles (culture-medias).
- Plusieurs agents ont mis dans leurs commits le lien de session réel au lieu de celui de REGLES.md.
- Sources non contournées (anti-robot, 403, 503) : budget.gouv.fr, Telepac, DREES, Dares, Légifrance, ameli.fr, agencedusport.fr, immobilier-etat.gouv.fr.

## Incidents de la session

- La branche de test agent/test-acces-renfort-donnees n'a pas pu être supprimée (le proxy coupe les push --delete) : à supprimer à la main.
- Les 7 agents de la seconde vague ont été coupés par la limite hebdomadaire d'usage, puis relancés après la remise à zéro ; tous ont terminé.
- Dans ~/wt/culture-medias, site/data/meta.json est modifié et non commité (effet de bord d'un test), laissé tel quel.
