# Recherche globale : inventaire et choix (19/11/2026)

## Existant avant ce travail

- `web/src/composants/recherche.ts` : moteur maison (normalisation accents, casse et ponctuation ; distance d'édition bornée, une faute par mot, deux à partir de 8 lettres ; abréviations « st », « ste » ; petits mots ignorés), champ de l'en-tête en combobox ARIA 1.2 (flèches, Entrée, Échap, statut annoncé).
- `web/src/ecrans/recherche.ts` : page `/recherche?q=`, résultats groupés par famille, « afficher plus », sources de l'index.
- `web/scripts/index-recherche.mjs` : index unique `_recherche.json` construit au build : pages, départements, communes (chaîne compacte par département), intercommunalités, missions, programmes, actions, opérateurs, prestations, organismes de la Sécurité sociale, grands impôts, et quelques entités publiques (entités contrôlées par l'État, prisons, régimes de retraite, ministères, 400 organisations de `entites/recherche_globale.json`).
- `web/src/ecrans/organisation.ts` : recherche propre à la page organisation, sur les fichiers publiés par préfixe de mot `entites/recherche/<préfixe>.json` (50 690 organisations qui ont une fiche).
- Manquaient : entreprises et associations (hors 400), parlementaires, glossaire, impôts de « Qui a voté », ligne de contexte avec montant, raccourci « / », règle d'ordre écrite. Le classement utilisait la taille des communes.

## Bibliothèques regardées (règle n°0)

| Bibliothèque | Licence | Dernière publication npm | Verdict |
|---|---|---|---|
| MiniSearch 7.2.0 | MIT | 16/09/2025 | inspiration seulement |
| FlexSearch 0.8.212 | Apache-2.0 | 06/09/2025 | inspiration seulement |
| Fuse.js 7.5.0 | Apache-2.0 | 09/08/2026 | inspiration seulement |

Le moteur maison fait déjà ce qu'il faut (normalisation, fautes de frappe, index compact, testé) pour 0 octet de dépendance en plus : il est gardé. Aucune des trois ne lit des morceaux publiés par préfixe sans les réindexer dans le navigateur.

## Ce qui change

- Index découpé par type : noyau `_recherche.json` (pages, budget, impôts, glossaire, départements, entités publiques), morceaux `_recherche/communes.json` et `_recherche/parlementaires.json`, lus à la première recherche.
- Organisations : lues à la demande dans les fichiers déjà publiés `entites/recherche/<préfixe>.json` (au plus 4 fichiers, mot le plus rare), et pour la ligne de contexte dans `_recherche/org/<début du SIREN>.json` (125 morceaux, 200 Ko au plus). SIREN ou SIRET exact : fiche directe.
- Ligne de contexte d'une organisation : SIREN, nombre de sources, département, montant le plus récent tel que publié par une seule source (une seule ligne cette année-là ; jamais une somme, ni dans une source ni entre sources).
- Parlementaires : députés des circonscriptions (vote nominatif publié) et auteurs d'amendements adoptés, groupe tel que publié au dernier vote ou amendement ; lien vers `/decisions/qui-a-vote?dep=&circo=` (la page ouvre la circonscription) ou vers la page de leurs amendements.
- Ordre : note du texte seulement, puis famille, nom le plus court, ordre alphabétique ; règle écrite sur la page et sous les suggestions. La taille des communes ne compte plus.
- Raccourci « / » (aria-keyshortcuts), rien de la saisie n'est gardé (ni stockage local, ni cookie), aucune requête hors de `data/`.

## Règle de nommage

Seuls les noms déjà publiés sont indexés : test `recherche globale sur les données publiées` (`web/tests/recherche.test.ts`) qui vérifie que chaque organisation des morceaux porte le nom des fichiers de recherche publiés pour son SIREN, et que chaque parlementaire indexé est nommé par un vote nominatif ou un amendement adopté publié.
