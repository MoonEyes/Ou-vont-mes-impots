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

## Déjà fait côté site (sans changement de format)

- Commune : titre, population et liens affichés dès la géographie (environ 7 Ko compressés) ; budgets ensuite, puis dotations, taux et subventions demandés seulement après les budgets.
- Calcul : moteur publicodes dans un Web Worker (TBT du passage saisie vers résultat : 2 000 ms avant, 100 ms après).
- Pied de page qui remontait pendant les chargements : CLS de 0,31 à 0,35 sur toutes les pages, 0 à 0,02 après.
