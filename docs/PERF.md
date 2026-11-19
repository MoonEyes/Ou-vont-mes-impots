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

### Allègement du 19/11/2026 (marge de taille)

Mesures sur `gh/main` (`6c42835a`, `npm run build`, 2 412 pages : 60 routes, 101 départements, 2 251 communes ; `dist/` : 15 360 fichiers, 811 Mo). Objectif demandé : HTML prérendu de 35 Mo au plus et 14 000 fichiers au plus, sans perdre de page indexable ni de contenu visible.

Où va le poids (avant) :

| Pages | Nombre | HTML | Page médiane / max |
|---|---|---|---|
| Communes | 2 251 | 41,1 Mo | 18,2 Ko / 18,8 Ko |
| Départements et routes | 161 | 5,2 Mo | département max 29,8 Ko ; routes les plus lourdes : `explorer/fonds-europeens` 222 Ko, `methode/glossaire` 165 Ko, `explorer/prestations` 152 Ko, `explorer/series` 140 Ko, `methode/fraicheur` 135 Ko |
| Total | 2 412 | 46,3 Mo | |

Page commune médiane (18,2 Ko) : en-tête HTML 4,7 Ko (dont JSON-LD 1,45 Ko), bandeau et menu 2,4 Ko, pied 2,4 Ko, contenu 8,8 Ko (dont budget 3,6 Ko, encadré « Où c'est » 0,9 Ko, « Signaler une erreur » 0,8 Ko). 23,1 Mo des 41,1 Mo de pages commune sont des morceaux identiques sur au moins 90 % d'entre elles (gabarit, encadrés, mentions de méthode). Aucune donnée n'est écrite en ligne dans les pages (deux balises `<script>` par page : le module et le JSON-LD) : rien à déplacer en JSON chargé à la demande.

Ce qui a été fait (`web/scripts/prerendre.mjs`), sans changement de l'affichage avec JavaScript :

| Mesure | HTML total | Gain |
|---|---|---|
| Avant | 46,3 Mo | |
| Blancs : la réduction de l'indentation était désactivée sur toutes les pages depuis l'ajout du `<textarea>` de « Signaler » ; elle protège désormais seulement le contenu de `<textarea>` et `<pre>`, supprime les blancs autour des balises de bloc et ramène les autres à un caractère. Titres et descriptions plus courts (section suivante, `docs/SEO.md`) | 42,6 Mo | 3,7 Mo |
| JSON-LD : objet `WebPage` retiré (il répétait titre, description et adresse canonique) ; une seule balise `theme-color` quand les deux variantes ont la même valeur ; « Signaler une erreur » posé par le script sur les 2 352 pages locales (sa liste de fichiers l'était déjà ; sans JavaScript, le contact reste sur la page Mentions) | 39,8 Mo | 2,8 Mo |
| JSON-LD : objet `WebSite` (nom du site, recherche) sur l'accueil seulement, la seule page lue pour le nom du site ; ailleurs, le fil d'Ariane | 39,4 Mo | 0,4 Mo |

Après : communes 34,5 Mo (médiane 15,3 Ko, max 15,7 Ko, 4,7 Ko transférés), départements 1,8 Mo (max 27,1 Ko), routes 3,0 Mo. Aucune page retirée : 2 412 pages, 2 408 dans le plan du site, comme avant.

Budgets de `web/tests/performance.test.ts` (mesure plus 10 %) : HTML total < 43,3 Mo, page commune < 17,2 Ko (< 5,2 Ko transférés), page département < 29,8 Ko, `dist/` 16 900 fichiers au plus. Le test vérifie aussi l'absence d'indentation, les sauts de ligne gardés dans `<textarea>` et l'absence de « Signaler » dans le HTML des pages commune.

**Objectif de 35 Mo non atteint (39,4 Mo).** Pistes mesurées et écartées dans ce périmètre :

- Générer des pages dans le navigateur : toutes les pages prérendues sont indexables sauf 3 ; aucune ne peut quitter le plan du site sans perte de référencement.
- Encadré « Où c'est » (0,9 Ko par commune) et pistes vides des barres (environ 0,6 Ko) : leur ajout par le script décalerait la mise en page en haut de page (CLS).
- Balises Open Graph qui répètent titre et description (environ 0,25 Ko) : gardées pour l'aperçu des liens partagés.
- Gabarit commun (bandeau, menu, pied, 4,1 Ko par page, 9,9 Mo au total) : `web/index.html`, hors de ce périmètre. Piste pour son responsable : le logo SVG est écrit deux fois (environ 0,9 Ko par page, 2,2 Mo) ; un fichier SVG partagé lu par `<use>` comme la trame de France demanderait des couleurs portées par `currentColor` ou des variables CSS héritées.
- « Voir aussi » des pages locales (0,34 Ko, liens déjà présents dans « Pour aller plus loin ») : gardé, c'est du contenu visible sans JavaScript.

### Nombre de fichiers (19/11/2026)

15 360 fichiers dans `dist/` : 12 836 de données (`data/`), 2 412 pages, 99 dans `assets/`, 14 à la racine. L'objectif de 14 000 ne dépend pas du prérendu (une page par adresse indexable) mais des données. Les plus nombreux :

| Dossier de `data/` | Fichiers | Lu par le site | Proposition (responsable du pipeline) | Gain |
|---|---|---|---|---|
| `revenus_communes/tranches/<annee>/<dep>.json` | 2 312 | non (téléchargement seulement) | un fichier par département, toutes années (`tranches/<dep>.json`) | 2 211 |
| `local/decisions/<siren>/<annee>.json` | 1 662 (1 264 collectivités) | oui (`ma_commune`, une année à la fois) | un fichier par collectivité, années en clés | 398 |
| `deliberations/collectivites/<siren>.json` | 1 210 | oui (`ma_commune`, `commune_investissement`, par collectivité) | regrouper par département (le site lirait le fichier du département) | environ 1 100 |
| `application_lois/mesures/`, `entites/fiches/`, `entites/recherche/` | 799, 762, 728 | oui | regroupements par tranche plus larges | à mesurer |

La première ligne suffit à repasser sous 14 000 (13 149). Le contrat (`docs/contrat_interface.md`, `datapackage.json`) change avec elle : ce n'est pas fait ici.

## Déjà fait côté site (sans changement de format)

- Commune : titre, population et liens affichés dès la géographie (environ 7 Ko compressés) ; budgets ensuite, puis dotations, taux et subventions demandés seulement après les budgets.
- Calcul : moteur publicodes dans un Web Worker (TBT du passage saisie vers résultat : 2 000 ms avant, 100 ms après).
- Pied de page qui remontait pendant les chargements : CLS de 0,31 à 0,35 sur toutes les pages, 0 à 0,02 après.
