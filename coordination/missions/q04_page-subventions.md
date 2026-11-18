Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-subventions ») : créer l'écran /beneficiaires/subventions (web/src/ecrans/subventions.ts, parent '/beneficiaires') à partir de site/data/subventions/ et site/data/associations/ (voir docs/contrat_interface.md, pipeline/subventions.py, pipeline/associations.py). Lis d'abord web/src/ecrans/beneficiaires.ts : ne duplique pas ce qu'il montre déjà, complète et relie.

La page montre en langage courant : combien l'État et ses opérateurs versent en subventions, à quels types de bénéficiaires (associations, entreprises, collectivités, établissements publics), par ministère et par année ; une recherche d'organisme bénéficiaire (personnes morales seulement ; les sommes non attribuables restent agrégées et affichées comme telles) avec chargement par morceaux. Chaque montant avec année, source, statut.

Fichiers à toi : web/src/ecrans/subventions.ts, web/tests/subventions.test.ts, tes fixtures.

Termine par le rapport final du brief.