# Performance : découpages à faire côté pipeline

Recette du 17/11/2026 (détail et mesures dans `docs/RECETTE.md`). Le site a été corrigé côté `web/` sans changer le format des données. Les points ci-dessous demandent un découpage des fichiers produits par le pipeline : ils sont décrits ici, pas faits.

Mesures : Lighthouse 13, profil mobile, 4G simulée (150 ms RTT, 1,6 Mbit/s), CPU ralenti x4, fichiers servis compressés (gzip, comme GitHub Pages).

## 1. Page commune : budgets et dotations par département trop gros pour une seule commune

La page `#/local/commune?insee=…` lit, pour afficher une seule commune, les fichiers de tout son département :

| Fichier | Compressé, médiane | p90 | max (62) |
|---|---|---|---|
| `local/budgets/communes/{dep}.json` | 174 Ko | 312 Ko | 477 Ko |
| `local/dotations/communes/{dep}.json` | 91 Ko | 138 Ko | 218 Ko |
| `local/taux/{dep}.json` | 20 Ko | 34 Ko | 54 Ko |

Après le rendu progressif côté site, le LCP est à 1,8 s (Nantes) et 2,0 s (Bordeaux), mais reste à 4,7 s pour une commune du Pas-de-Calais (62) : le seul fichier de budgets fait 477 Ko compressés, soit environ 2,5 s de transfert en 4G simulée.

Proposition (pipeline, `local.py`) :

- Découper `local/budgets/communes/{dep}.json` en tranches de code INSEE, par exemple `local/budgets/communes/{dep}/{3 premiers chiffres du code}.json` (même structure `millesime`, `source`, `annees`, `agregats`, `collectivites`, limitée aux communes de la tranche), ou un fichier par commune pour les départements de plus de 500 communes.
- Même découpage pour `local/dotations/communes/{dep}.json` et `local/taux/{dep}.json`.
- Ajouter dans `local/geo/{dep}.json`, pour chaque commune, le chemin de son fichier (`fichier_budget`, `fichier_dotations`), comme le fait déjà l'arbre de l'État avec `fichier` : le site suivra ce chemin s'il existe et gardera le fichier départemental en repli.
- Cible : moins de 30 Ko compressés par commune pour les trois fichiers, LCP sous 2,5 s partout.

## 2. Vie politique : fichiers de candidats chargés en entier au clic

`vie_politique/candidats/departementales_2015.json` (2,5 Mo, 380 Ko compressés), `departementales_2021.json` (2,1 Mo, 327 Ko), `legislatives_2017.json` (1,7 Mo, 190 Ko) sont lus en entier quand on ouvre une élection, alors que la table n'affiche que 50 lignes par page.

Proposition : un fichier par département pour les élections locales et législatives (`vie_politique/candidats/{election}/{dep}.json`), avec un index national léger (totaux, liste des départements) ; l'écran charge l'index puis le département choisi.

## 3. Fichiers non lus par le site

`local/decisions/{siren}/{annee}.json` (63 Mo au total, jusqu'à 1,5 Mo par fichier) et `local/dotations/epci.json` (3 Mo) ne sont lus par aucun écran : ils sont copiés dans `dist/` à chaque construction. Si leur publication sert seulement au téléchargement des données, les sortir de `site/data` (ou les lister dans un dossier « téléchargements ») réduirait le temps de déploiement sans effet sur les pages.

## Budgets du prérendu

Mesures du 18/11/2026 (`npm run build`, données du 17/11/2026 : 2 380 pages dont 101 départements et 2 251 communes). Poids transféré : gzip niveau 9, comme un hébergeur qui compresse. Les budgets sont vérifiés par `web/tests/performance.test.ts` sur le site construit (`dist/prerendu.json` et pages réelles).

| Mesure | Avant | Après | Budget |
|---|---|---|---|
| HTML prérendu, total | 99,3 Mo | 62,2 Mo | < 70 Mo |
| `dist/`, total (dont 425 Mo de données) | 527 Mo | 490 Mo | |
| Page commune, brute (médiane / max) | 41,8 Ko / 42,5 Ko | 26,0 Ko / 26,7 Ko | max < 30 Ko |
| Page commune, transférée (médiane ; Nantes) | 8,9 Ko ; 8,9 Ko | 5,9 Ko ; 6,0 Ko | < 7 Ko |
| Page département, brute (médiane / max) | 53,3 Ko / 94,0 Ko | 37,5 Ko / 78,2 Ko | max < 85 Ko |
| Encadré « Où c'est » dans le HTML | 16,4 Ko (3,1 Ko transférés) | 1,0 Ko | < 1,5 Ko |
| Fond de carte partagé `assets/trame-france-*.svg` | | 9,0 Ko (1,1 Ko transféré, une fois puis en cache) | < 12 Ko |

Cause de la hausse (59 à 99 Mo) : la carte de France en trame (101 carrés, chacun avec son lien) était écrite en entier dans chacune des 2 352 pages département et commune, 16,4 Ko par page.

Ce qui a changé (`web/src/composants/trame.ts`) :

- Les 101 carrés et leurs numéros sont dans un seul fichier, `web/src/composants/trame-france.svg`, émis par Vite dans `assets/` avec une empreinte (mis en cache par le navigateur) et dessiné par `<use href="…/assets/trame-france-….svg#trame-france">`. Le fichier n'a ni couleur ni police : contour, fond, couleur des numéros et police (Figtree) viennent de l'élément `<use>` de la page, donc le thème sombre est suivi. `web/scripts/prerendre.mjs` réécrit son adresse relativement à chaque page.
- Le HTML de chaque page ne contient plus que le carré de son département, avec son lien, au même endroit : rendu identique, avec ou sans JavaScript.
- Accessibilité : le nom de la carte, le département mis en avant et la légende « Ton département » sont inchangés. Les 100 autres liens (100 arrêts de tabulation avant le contenu de la page) sont remplacés par un lien vers la carte complète de la page « Chez moi », qui garde un lien par département, et par le fil d'Ariane.
- `dist/prerendu.json` donne aussi `octets_page_commune_max` et `octets_page_departement_max`.

### Allègement des pages locales (18/11/2026)

Les blocs ajoutés depuis avaient ramené le HTML à 69,9 Mo pour un budget de 70 Mo. Mesure (Nantes, 28,4 Ko) : en-tête HTML et habillage 11,8 Ko, contenu 18,0 Ko, dont 7,5 Ko de cartes recopiées dans chaque commune d'un même département ou d'une même intercommunalité (bloc communal, département, région) et 5,5 Ko de tableaux et d'attentes du détail.

| Mesure | Avant | Après | Budget (après + 10 %) |
|---|---|---|---|
| HTML prérendu, total | 69,9 Mo | 43,2 Mo | < 47,5 Mo |
| Page commune, brute (médiane / max) | 28,2 Ko / 29,0 Ko | 17,0 Ko / 17,6 Ko | max < 19,4 Ko |
| Page commune, transférée (médiane / max) | 6,7 Ko / 6,9 Ko | 5,0 Ko / 5,0 Ko | < 5,5 Ko |
| Page département, brute (médiane / max) | 40,4 Ko / 81,1 Ko | 18,2 Ko / 28,4 Ko | max < 31,2 Ko |

Ce qui reste dans le HTML (référencement, lecture sans JavaScript) : titre, description, fil d'Ariane, introduction (population, intercommunalité, département, région), chiffres clés, budget de la commune (ou du département) avec sa source, liens vers les fichiers de données, liens de sortie, liste des communes qui ont leur page. Ce qui est rendu dans le navigateur, à partir des mêmes fichiers JSON déjà publiés et mis en cache : budgets de l'intercommunalité, du département et de la région ; dotations, taux, subventions, projets, loi SRU, organismes ; sur la page département, la liste des communes de 5 000 habitants ou moins (leur page générique ne se lit qu'avec JavaScript). Le HTML prérendu les annonce dans une liste « s'affichent aussi ». Un nouveau bloc s'ajoute à `DETAIL_COMMUNE` (`web/src/ecrans/commune.ts`) ou `DETAIL_DEPARTEMENT` (`departement.ts`) : une ligne de plus dans le HTML. Le prérendu ne garde de l'objet `WebSite` (JSON-LD) que son nom, son adresse et son identifiant hors de l'accueil, et ramène l'indentation entre balises à un saut de ligne. Avec JavaScript, la page affichée est inchangée (même structure, 14 titres de section à Nantes) ; axe-core sans erreur avec et sans JavaScript, 390 et 1 280 px ; décalage de mise en page nul.

## Déjà fait côté site (sans changement de format)

- Commune : titre, population et liens affichés dès la géographie (environ 7 Ko compressés) ; budgets ensuite, puis dotations, taux et subventions demandés seulement après les budgets.
- Calcul : moteur publicodes dans un Web Worker (TBT du passage saisie vers résultat : 2 000 ms avant, 100 ms après).
- Pied de page qui remontait pendant les chargements : CLS de 0,31 à 0,35 sur toutes les pages, 0 à 0,02 après.
