Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « suivre-un-euro ») : créer l'écran /suivre-un-euro (web/src/ecrans/suivre.ts, parent '/explorer') : un parcours pas à pas qui suit 1 € de la fiche de paie jusqu'à son usage final (par exemple 1 € de CSG → caisse nationale d'assurance maladie → hôpitaux → …), en s'appuyant sur les données de traçabilité (site/data/tracabilite/, web/src/composants/tracabilite.ts) et le composant web/src/composants/fil-euro.ts (à toi pour cette mission). La personne choisit le prélèvement de départ (CSG, cotisation retraite, impôt sur le revenu, TVA…) ; chaque étape montre le montant sur 1 € (ou 100 €), l'organisme, la source et le statut (tracé, approché, non publié) ; là où la piste s'arrête faute de publication, la page le dit clairement. Mouvement seulement en réponse à une action de la personne, respect de prefers-reduced-motion.

Fichiers à toi : web/src/ecrans/suivre.ts, web/src/composants/fil-euro.ts, web/tests/suivre.test.ts, tes fixtures.

Termine par le rapport final du brief.