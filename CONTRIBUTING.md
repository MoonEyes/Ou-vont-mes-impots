# Contribuer

Merci de ton aide. Le projet vit de données publiques : la priorité est l'exactitude et la traçabilité, avant les nouveautés.

## Avant de commencer

1. Lis le `README.md` (architecture, commandes) et la partie concernée de `docs/contrat_interface.md`.
2. Pour une nouvelle source ou un nouveau bloc du site, ouvre d'abord une issue : quelle donnée, quel jeu public, quel millésime, quelle licence.

## Proposer un changement

1. Crée une branche depuis `main`.
2. Installe les dépendances : `pip install -r requirements.txt` (et `cd web && npm ci` pour le site).
3. Fais le changement, avec ses tests (`tests/` pour le pipeline, `collecte/tests/` pour la collecte, `web/tests/` pour le site).
4. Vérifie que tout est vert :
   ```bash
   frictionless validate datapackage.json
   python docs/valider_contrat.py --quiet
   pytest -q
   ```
5. Ouvre une pull request qui dit ce qui change, pourquoi, et la source de chaque nouveau chiffre.

## Règles du dépôt

- **Nouveau fichier dans `site/data`** : schéma dans `docs/schemas/`, ligne dans le validateur (`docs/valider_contrat.py`, liste `FICHIERS`), section dans `docs/contrat_interface.md`. Ajouter un champ ou un fichier = version mineure du contrat ; renommer ou supprimer = version majeure.
- **Chaque fichier** porte `millesime` et `source`. Un montant écarté est publié avec sa raison.
- **Personnes physiques** : jamais nommées (seules exceptions : candidats des comptes de campagne, liste blanche de champs). Une source qui en contient va dans `data/lake/_restreint/`.
- **Données générées** (`site/data`, `data/raw`, `data/processed`) : régénère-les avec le pipeline, ne les modifie pas à la main. Une erreur de données se corrige dans le code du pipeline ou se signale dans une issue.
- **Réseau** : les commandes de collecte sont reprenables et bornées en durée ; les commandes de production et les tests fonctionnent sans réseau.
- Messages de commit en français, à l'impératif ou descriptifs, une idée par commit.

## Code de conduite

La participation au projet suit le `CODE_OF_CONDUCT.md`.
