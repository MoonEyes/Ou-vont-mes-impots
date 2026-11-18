Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « export-csv-citer ») : amélioration progressive sur tout le site : après le rendu de chaque écran, chaque tableau de données (<table> du contenu principal) reçoit deux actions discrètes : « Télécharger (CSV) » (fichier généré dans le navigateur, séparateur point-virgule et virgule décimale pour Excel en français, UTF-8 avec BOM, en-têtes, nom de fichier parlant) et « Citer » (texte de citation prêt à copier : titre du tableau, site, source et millésime des données, URL de la page, date de consultation ; copie dans le presse-papiers avec annonce accessible). Un composant web/src/composants/exporter.ts et un seul crochet ajouté dans web/src/routeur.ts par script sous flock (l'agent glossaire ajoute aussi un crochet : relis le fichier juste avant). Aucune bibliothèque externe lourde, aucune requête externe.

Fichiers à toi : web/src/composants/exporter.ts, web/tests/exporter.test.ts, tes fixtures.

Termine par le rapport final du brief.