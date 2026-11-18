Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-comparaison-europe ») : créer l'écran /explorer/comparaison-europe (web/src/ecrans/comparaison_europe.ts, parent '/explorer') à partir de site/data/comparaison/ et site/data/cofog.json (voir docs/contrat_interface.md, pipeline/europe_comparaison.py). Lis d'abord web/src/ecrans/ue.ts (ce que la France verse à l'Union européenne) : autre sujet, relie les deux pages sans les mélanger.

La page montre en langage courant : la dépense publique et les prélèvements obligatoires de la France et des autres pays de l'Union, en part du PIB et par habitant (standard de pouvoir d'achat si disponible), par grande fonction (classification COFOG expliquée simplement), sur les années disponibles. Neutralité stricte : aucun palmarès, aucune couleur de valeur, la France seulement repérée ; ordre alphabétique ou par valeur au choix ; limites de comparaison expliquées (périmètres, systèmes de retraite et de santé différents). Chaque chiffre avec année, source (Eurostat), statut.

Fichiers à toi : web/src/ecrans/comparaison_europe.ts, web/tests/comparaison_europe.test.ts, tes fixtures.

Termine par le rapport final du brief.