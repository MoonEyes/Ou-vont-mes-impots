Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-territoires ») : rendre visibles site/data/territoires/ et site/data/local_satellites/ (voir docs/contrat_interface.md, pipeline/territoires.py, pipeline/local_satellites.py). Les écrans web/src/ecrans/departement.ts et web/src/ecrans/commune.ts sont à toi pour cette mission (le design « billet découpé » y est en place, dont la carte « Où c'est » : garde-le intact, ne touche pas à web/src/composants/trame.ts qui appartient à l'agent performance). Ajoute aux pages département et commune les blocs utiles tirés de ces données (dépenses de l'État dans le territoire, budgets annexes, syndicats et autres organismes rattachés), ou crée un écran dédié /local/territoires si c'est plus clair ; justifie ton choix. Les pages commune sont prérendues pour 2 251 communes : garde un poids raisonnable.

Fichiers à toi : web/src/ecrans/departement.ts, web/src/ecrans/commune.ts, un éventuel web/src/ecrans/territoires.ts, web/tests/territoires.test.ts, tes fixtures.

Termine par le rapport final du brief.