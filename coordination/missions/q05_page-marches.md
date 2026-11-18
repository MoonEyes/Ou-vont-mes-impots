Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-marches ») : créer l'écran /beneficiaires/marches (web/src/ecrans/marches.ts, parent '/beneficiaires') à partir de site/data/marches/ (voir docs/contrat_interface.md, pipeline/marches.py ; tu peux corriger ce pipeline et ses données, l'agent d'origine a fini).

La page montre en langage courant : les marchés publics (données essentielles de la commande publique) : montants par année, par acheteur, par type (travaux, fournitures, services), par secteur et par région, et les principaux titulaires (personnes morales seulement ; entrepreneurs individuels agrégés). Point signalé : des valeurs aberrantes en 2021 (288 Md€ cumulés, erreurs de saisie probables dans la source) : rends-les visibles et explique la règle retenue (exclusion des totaux avec mention et compteur, ou signalement), jamais additionnées sans avertissement ; documente la règle dans le contrat. Chaque montant avec année, source, statut.

Fichiers à toi : web/src/ecrans/marches.ts, web/tests/marches.test.ts, tes fixtures, et l'axe marches si une correction est nécessaire.

Termine par le rapport final du brief.