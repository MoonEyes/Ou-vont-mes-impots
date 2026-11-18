Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « comparer-communes ») : créer l'écran /local/comparer (web/src/ecrans/comparer.ts, parent '/local') : deux communes côte à côte, choisies par département puis commune (même mécanique que les pages locales existantes), avec les mêmes échelles : dépenses et recettes par habitant, dette par habitant, épargne, investissement, dotations de l'État, taux d'imposition locaux votés, et le revenu fiscal médian si l'axe revenus_communes est déjà commité dans site/data (un autre agent le produit ; sinon prévois-le proprement et signale-le). Aucune « meilleure » commune, aucun classement, aucune couleur de valeur ; une phrase rappelle que les communes n'ont pas les mêmes compétences ni la même taille. Lien partageable (paramètres dans l'URL). Réutilise les chargeurs de local.ts, commune.ts et departement.ts sans les modifier (commune.ts et departement.ts sont à l'agent territoires).

Fichiers à toi : web/src/ecrans/comparer.ts, web/tests/comparer.test.ts, tes fixtures.

Termine par le rapport final du brief.