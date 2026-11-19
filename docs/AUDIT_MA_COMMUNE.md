# Audit « Ma commune » (19/11/2026)

Promesse : je tape mon code postal ou le nom de ma commune, j'obtiens en un écran ce que ma commune, mon intercommunalité, mon département et ma région font de l'argent public, avec les bénéficiaires locaux nommés (personnes morales seulement), les projets et délibérations, et les comparaisons avec des communes semblables.

## 1. Ce qui existait avant ce travail

| Écran ou donnée | Ce qu'il apporte | Limite pour la promesse |
|---|---|---|
| `/local` (ecrans/local.ts) | choix du département puis de la commune (deux listes) | pas de code postal, pas de recherche par nom |
| `/local/commune` (ecrans/commune.ts, 2 251 pages prérendues au-delà de 5 000 habitants) | budget de la commune par nature, intercommunalité ou bloc communal, département, région ; dotations, taux, subventions, projets, SRU, organismes, investissement et délibérations (au défilement) | page longue ; budgets par nature seulement ; pas de bénéficiaires nommés ni de fonds européens par commune |
| `/local/departement`, `/local/comparer`, `/local/croiser`, `/local/projets` | communes d'un département, deux communes côte à côte, communes semblables (densité, strate, aire d'attraction), projets aidés par l'État | chacun à part, aucune page ne les assemble |
| `local/fonctions/` (pipeline/local_fonctions.py) | dépenses par grande fonction des communes (publiées si plus de 3 500 habitants ou volontairement), EPCI et régions, 2023 à 2025 | **aucun écran ne les lisait** |
| `local/decisions/` | subventions votées publiées au format national (SCDL), bénéficiaires personnes morales nommés | 32 communes, 14 intercommunalités, 15 départements, 8 régions publient ; non rattachées à la commune du bénéficiaire |
| `fonds_europeens/operations/` | opérations nommées avec `commune_insee` | six listes d'autorités de gestion (Bretagne, Pays de la Loire, Normandie, Île-de-France, La Réunion) |
| `deliberations/`, `territoires/`, `projets_subventionnes/`, `typologies/` | délibérations publiées, projets DETR, DSIL, DPV, DSID et Fonds vert, typologies et quartiles par case | déjà prêts à l'emploi |

## 2. Ce qui manquait

1. **Codes postaux** : aucune table dans le dépôt ni dans l'entrepôt (`data/lake`). Le seul code postal lu (opérations FEDER de Bretagne) n'est pas une table de correspondance.
2. Un champ unique code postal ou nom, avec propositions, sans requête hors du site.
3. Une page qui assemble les blocs en un écran, chaque bloc sourcé, daté, et qui dit pourquoi quand la donnée manque.
4. Un lien depuis le résultat du simulateur.

## 3. Source des codes postaux (règle n°0)

| Trouvaille | Verdict | Licence | Date |
|---|---|---|---|
| La Poste, base officielle des codes postaux (data.gouv.fr `base-officielle-des-codes-postaux`, data.laposte.fr `laposte-hexasmal`) | réutilisable tel quel | Licence Ouverte 2.0 | fichier du 17/11/2026 |
| geo.api.gouv.fr, champ `codesPostaux` (dépôt etalab/decoupage-administratif) | inspiration seulement (requête externe à chaque frappe exclue) | Licence Ouverte (données), MIT (code) | dérivé de la même base |
| Paquet npm `codes-postaux` (BaseAdresseNationale) | inspiration seulement (un seul fichier d'environ 2 Mo) | MIT, Licence Ouverte | même base |
| `site/data/local/geo` (code officiel géographique, population) | réutilisable tel quel | Licence Ouverte | versionné |

Collecte : entrée `ma_commune_codes_postaux` de `collecte/catalogue.json`, `collecte/collecte.py` (contrôle `collecte/integrite.py`, CSV complet, 39 192 lignes, 1,6 Mo).

## 4. Cas particuliers relevés dans la base

- **Codes postaux partagés** : 4 200 codes sur 6 187 desservent plusieurs communes (jusqu'à 46) : toutes sont proposées, l'écran demande de choisir ; les localités de la ligne 5 desservies sous ce code sont données en précision.
- **Communes à plusieurs codes postaux** : 359 ; tous listés.
- **Communes nouvelles** : la ligne 5 donne souvent le nom de la commune déléguée (ancienne commune) ou d'un lieu-dit ; 4 591 localités trouvables par leur nom, toujours rattachées à la commune actuelle et marquées « localité ». La base de La Poste est alignée sur le code officiel géographique 2026 (les 34 875 communes sont couvertes) ; le pipeline s'arrête si un code Insee de La Poste n'existe pas dans `local/geo` (décalage après une fusion).
- **Paris, Lyon, Marseille** : La Poste donne le code de l'arrondissement municipal (75101 à 75120, 69381 à 69389, 13201 à 13216). Seule la commune publie des comptes : le code postal mène à 75056, 69123 ou 13055 et l'arrondissement est écrit en précision ; 45 arrondissements trouvables par leur nom.
- **Hors périmètre** : collectivités d'outre-mer (975, 977, 978, 986 à 989), Clipperton et Monaco, 141 codes postaux : absents des comptes publiés par la DGFiP et l'OFGL, message dédié à l'écran.

## 5. Ce qui a été fait

- `pipeline/ma_commune.py` : `site/data/ma_commune/index.json`, `cp/<2 chiffres>.json` (96 fichiers), `noms/<préfixe>.json` (126 fichiers), 4,1 Mo au total, 128 Ko au plus par fichier ; contrat 2.71, trois schémas, `tests/test_ma_commune.py`.
- `/local/ma-commune` (web/src/ecrans/ma_commune.ts et ma_commune_recherche.ts) : champ unique branché aussi sur `/local` ; synthèse par commune : budgets par fonction sur 100 € (commune, intercommunalité, région ; à défaut par nature avec le motif ; département par nature), subventions publiées par la commune et l'intercommunalité (montants les plus élevés de la dernière année, personnes morales seulement), opérations des fonds européens situées dans la commune, projets aidés par l'État, délibérations, repères parmi les communes de même densité et de même strate. Rien n'est prérendu par commune (aucune nouvelle page HTML par commune ; budgets de `web/tests/performance.test.ts` inchangés).
- Résultat du simulateur : la carte « Et dans ma commune ? » mène à `/local/ma-commune?insee=` (code Insee seul, jamais le salaire).

## 6. Ce qui manque encore

- Dépenses par fonction des **départements** : publiées pour quelques départements pilotes seulement (`local/budgets/fonctions/`) ; la synthèse affiche le département par nature.
- **Bénéficiaires locaux** des subventions du département et de la région : les listes publiées ne donnent pas la commune du bénéficiaire ; non rattachables sans géocodage SIRENE (piste : commune du siège dans le stock SIRENE, déjà lu par `pipeline/sirene.py`).
- **Fonds européens par commune** : six listes d'autorités de gestion seulement ; ailleurs la page renvoie aux montants par région.
- **Délibérations** : 3,3 % des communes publient au format national.
- Communes de moins de 3 500 habitants : présentation par fonction facultative, la synthèse montre la présentation par nature (OFGL).
