Lis en entier coordination/REGLES.md (dans le dossier de coordination indiqué par ton coordinateur) avant d'agir : il s'impose à toi.

Ta mission (agent « page-numerique-etat ») : créer l'écran /explorer/numerique-etat (web/src/ecrans/numerique_etat.ts, parent '/explorer') à partir de site/data/numerique_etat/ (voir docs/contrat_interface.md, pipeline/numerique_etat.py ; tu peux corriger ce pipeline et ses données, l'agent d'origine a fini). Vérifie d'abord ce qui est déjà affiché ailleurs et ne duplique pas.

La page montre en langage courant : ce que l'État dépense pour le numérique (grands projets informatiques, coûts initiaux et réévalués, délais, ministères porteurs), les écarts entre budget prévu et réel tels que publiés (sans qualificatif), l'évolution. Point signalé à traiter : le mot « porteurs » a été relevé ; vérifie qu'il désigne uniquement des administrations ou ministères et qu'aucune personne physique (chef de projet, directeur) n'est nommée dans les données publiées ni affichées ; corrige sinon. Chaque chiffre avec année, source, statut.

Fichiers à toi : web/src/ecrans/numerique_etat.ts, web/tests/numerique_etat.test.ts, tes fixtures, et l'axe numerique_etat si une correction est nécessaire.

Termine par le rapport final du brief.