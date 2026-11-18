Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-recouvrement ») : créer l'écran /explorer/recouvrement (web/src/ecrans/recouvrement.ts, parent '/explorer') à partir de site/data/recouvrement/ (voir docs/contrat_interface.md, pipeline/recouvrement.py). Vérifie d'abord ce qui est déjà affiché ailleurs et ne duplique pas.

La page montre en langage courant : comment l'impôt et les cotisations sont collectés (DGFiP, Urssaf, douanes), le coût de la collecte quand il est publié, les montants issus du contrôle fiscal et social (droits et pénalités notifiés, montants effectivement encaissés : les deux, sans les confondre), les estimations d'écart de recouvrement ou de fraude avec leur producteur, leur méthode et leur fourchette (plusieurs estimations côte à côte, jamais tranchées ni additionnées). Aucun cas individuel. Neutralité stricte du vocabulaire.

Fichiers à toi : web/src/ecrans/recouvrement.ts, web/tests/recouvrement.test.ts, tes fixtures.

Termine par le rapport final du brief.