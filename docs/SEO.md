# Référencement : prérendu, plan du site, données structurées

Constat de départ (audit du 17/11/2026) : les moteurs de recherche ne voyaient qu'une page. Les adresses étaient des fragments (`#/explorer/etat`), qui ne sont pas indexés, et le HTML servi était vide avant l'exécution du JavaScript.

Depuis : chaque route a une vraie page HTML, lisible sans JavaScript, avec son titre, sa description, son adresse canonique, ses balises Open Graph et son fil d'Ariane en données structurées. Le JavaScript reprend ensuite la main (navigation sans rechargement). Rien n'est ajouté au site servi : aucune dépendance d'exécution, aucune requête externe, CSP inchangée.

## Outil retenu (Règle n°0 : chercher l'existant avant d'écrire)

| Outil | Licence | Dernière activité | Verdict |
|---|---|---|---|
| happy-dom 21 + API de Vite (`ssrLoadModule`) | MIT | commit du 26/10/2026 | **Réutilisé tel quel.** Déjà dans `devDependencies` (tests) : les écrans du site sont exécutés au build, sans rien installer. |
| vite-prerender-plugin (Preact) | MIT | commit du 25/09/2026 | À adapter : même principe (une fonction de rendu appelée au build), mais une dépendance de plus et sa propre découverte des liens ; non retenu. |
| vite-ssg | MIT | publication npm du 05/02/2026 | Inspiration seulement : réservé à Vue. |
| vike (ex vite-plugin-ssr) | MIT | commit du 16/11/2026 (vite-plugin-ssr : npm, 22/09/2023, remplacé par vike) | Inspiration seulement : c'est un cadre complet (routage par fichiers, rendu serveur) qui imposerait de réécrire le site. |
| vite-plugin-prerender | MIT | publication npm du 05/09/2022 | Non retenu : plus maintenu, repose sur Puppeteer. |
| puppeteer | Apache-2.0 | commit du 17/11/2026 | Non retenu pour le build : 2 380 pages dans un navigateur, c'est un téléchargement de Chrome et plusieurs minutes en intégration continue. Gardé pour la recette (hors dépôt). `web/scripts/og.html` est seulement la source de l'image de partage. |

Dates relevées le 17/11/2026 (dernier commit de la branche par défaut quand le dépôt est lisible, sinon dernière publication npm).

## Fonctionnement

- `web/src/chemins.ts` : conversion entre la notation interne des écrans (`#/explorer/etat?m=lfi2025`, celle des anciens fragments) et les chemins publics (`explorer/etat/?m=lfi2025`). Les écrans n'ont pas changé d'écriture.
- `web/scripts/prerendre.mjs`, lancé par `npm run build` après `vite build` : rend chaque route avec le routeur du site dans happy-dom (`fetch` lit `dist/data` sur le disque, toute autre adresse est refusée), pose le résultat dans le gabarit `dist/index.html` de Vite et écrit `dist/<chemin>/index.html`. Les attributs `style` sont retirés (interdits par la CSP ; le script repose les largeurs des barres).
- `web/src/main.ts` : une page prérendue porte `data-racine` sur `<html>` (chemin relatif vers la racine du site). Le script passe alors en vrais chemins : History API, liens internes suivis sans rechargement, données lues sous la racine. Sans cet attribut (développement avec `npm run dev`, tests), le site reste en fragments.
- Anciennes adresses : `…/#/explorer/etat?m=lfi2025` est remplacée par `…/explorer/etat/?m=lfi2025` sans rechargement ; les redirections V1 (`#/paie`, `#/etat`…) continuent de s'appliquer.
- Les liens du HTML sont relatifs (`../../calcul/`) : le même build fonctionne à la racine d'un domaine et sous `/Ou-vont-mes-impots/`.
- Pas de `404.html` : une adresse inconnue répond 404 (GitHub Pages et Cloudflare, `not_found_handling = "none"`). Les deux hébergeurs redirigent `/explorer/etat` vers `/explorer/etat/`.

## Pages produites

| Pages | Nombre | Adresse | Indexée |
|---|---|---|---|
| Routes du site | 28 | `/explorer/etat/` | oui, sauf 3 |
| Départements | 101 | `/local/44-loire-atlantique/` | oui |
| Communes de plus de 5 000 habitants | 2 251 | `/local/44109-nantes/` | oui |

Trois pages ne sont ni indexées (`noindex, follow`) ni dans le plan du site, parce qu'elles n'ont pas de contenu propre sans saisie ou sans paramètre : `/calcul/resultat/`, `/local/commune/` (communes de 5 000 habitants ou moins, par `?insee=`) et `/local/departement/`.

Pages commune : titre « Budget de Nantes (Loire-Atlantique) : dépenses, dotations, taux », avec l'élision et les contractions (« d'Angers », « du Mans », « des Abymes »). Le nom du département remplace le code postal, absent de `site/data/local`. Le contenu est celui de l'écran du site : population, dépenses et dépenses par habitant, dette, dotation globale de fonctionnement, taux votés (au moins trois chiffres propres à la commune, contrôlé par test sur chacune). Le seuil est `SEUIL_PAGE_COMMUNE` dans `web/src/chemins.ts` ; l'abaisser suffit à produire plus de pages.

Mesures du 17/11/2026 (données complètes) : 2 380 pages, 53,9 Mo de HTML (environ 22 Ko par page). `dist/` au dernier build : 7 929 fichiers, 478 Mo, dont l'essentiel est `data/` (le nombre varie avec les données : 7 055 fichiers et 399 Mo deux heures plus tôt). Prérendu 42 s et build complet 73 s sur une machine peu chargée (jusqu'à 6 min quand d'autres traitements occupaient tous les processeurs). Mémoire : le document happy-dom est rouvert à chaque département, sinon le prérendu dépasse 3 Go. Limite Cloudflare : 20 000 fichiers ; le script échoue au-delà et écrit le bilan dans `dist/prerendu.json`. Toutes les communes (34 875) dépasseraient la limite : au-delà de 12 000 pages environ, passer `data/local` en R2 (`docs/DEPLOIEMENT.md`) ou servir les petites communes autrement.

## Balises et données structurées

- `title`, `meta description`, `link rel="canonical"` et Open Graph : propres à chaque page, uniques (test). Carte X/Twitter : seule `twitter:card` est écrite, X reprend titre, description et image d'Open Graph. Image de partage `og.png` générée au build depuis `web/scripts/og.html` par Chrome sans interface quand il est présent, sinon l'image versionnée. Titres et descriptions des routes : `web/src/routes.ts` (`titrePage`, `description`), soumis au lexique neutre.
- JSON-LD : `WebSite` partout (avec `SearchAction` vers `/recherche/?q=` sur l'accueil) ; `WebPage` et `BreadcrumbList` sur chaque page sauf l'accueil ; `Dataset` (`@id` `<site>#donnees`) sur l'accueil.
- `Dataset` : les champs viennent de `docs/datapackage/schemaorg.jsonld`, produit par `pipeline/datapackage.py` (`keywords`, `temporalCoverage`, `version`, `sameAs`, `distribution`). `dateModified` est la date des données, `spatialCoverage` la France, `url` l'adresse du site, `creator` « Projet citoyen Où vont mes impôts ». Une distribution n'est gardée que si son fichier existe dans `dist/data` (une par famille, 25 au plus). Rien n'est rédigé à la main.
- `sitemap.xml` : les pages indexables. `lastmod` est la date des données, pas celle du build : `data/mise_a_jour.json` (`genere_le`), à défaut `data/meta.json` ; pour les pages locales, la date de collecte de `data/local/index.json`.
- `robots.txt` : autorise tout et déclare le plan du site.

## Contenu aligné sur les recherches

Sans changer le cadrage du site (« ce que tu verses », `docs/NEUTRALITE.md`) : intertitre « À quoi servent mes impôts ? » sur l'accueil, avec des liens vers les grands ensembles ; titre de `/calcul` « Combien je verse d'impôts et de cotisations : calcul à partir du salaire » ; `/local` titré « Budget de ma commune », avec la liste des 101 départements. L'accueil affiche son texte sans attendre les données ; le nombre de sources complète ensuite sa phrase, sans décalage de mise en page.

## Performances

- Le contenu prérendu reste affiché jusqu'à ce que l'écran soit complet, puis il est remplacé d'un coup (`web/src/routeur.ts`) : pas d'état « Chargement… », pas de décalage.
- Les trois polices du premier écran sont préchargées (`<link rel="preload">`, même origine). Sans cela, le texte désormais présent dès le premier affichage se décalait au remplacement de la police de repli (CLS 0,03 à 0,04).
- Lighthouse mobile, avant (build de la recette) et après, même machine le 17/11/2026 : LCP accueil 1,6 s vers 0,8 s, État 2,5 s vers 0,8 s, Nantes 1,8 s vers 0,8 s, Arras 1,7 s vers 0,8 s ; CLS 0 partout ; accessibilité 100, bonnes pratiques 100.
- Réserve : la machine de mesure était saturée par d'autres traitements (charge 12 à 15). Le temps de blocage (TBT) relevé par Lighthouse y est instable (30 à 1 370 ms sur la même page) et les scores de performance (75 à 100) ne sont pas comparables à ceux de `docs/RECETTE.md`. Mesurées directement (processeur ralenti 4 fois, 3 passages), les tâches longues sont du même ordre avant et après (État : 57 à 188 ms avant, 96 à 274 ms après). À refaire sur une machine au repos ou sur l'adresse publique.
- SEO Lighthouse 92 : seul échec, `robots.txt`, lié au sous-répertoire (voir ci-dessous).

## Limites et points d'attention

- **`robots.txt` est ignoré sur GitHub Pages en sous-répertoire.** Les robots ne lisent que `https://mooneyes.github.io/robots.txt`, pas `/Ou-vont-mes-impots/robots.txt`. Le fichier sert dès que le site est à la racine d'un domaine (Cloudflare). Le site principal étant sur Cloudflare, c'est son plan du site qu'on déclare dans la Search Console et Bing Webmaster Tools (`docs/AUDIT_SEO.md`, « À faire »).
- **Adresse publique (19/11/2026).** Une seule source : `web/adresse-site.json` (hôte Cloudflare tant que le domaine définitif n'existe pas). Canonique, Open Graph, plan du site, `robots.txt`, carte de partage, référence d'un signalement et pied d'impression la reprennent ; `OVMI_URL_SITE` la remplace le temps d'un build. La copie GitHub Pages désigne donc l'hôte principal comme canonique ; `OVMI_COPIE_SECOURS=1` la passe en plus en `noindex` sans plan du site. Audit et mesures : `docs/AUDIT_SEO.md`.
- **Ne pas relancer le prérendu seul sur un `dist/` déjà prérendu** : `dist/index.html` est alors la page d'accueil et non le gabarit. Le script le détecte et demande de relancer `vite build`.
- Les barres proportionnelles n'ont pas de largeur sans JavaScript (la CSP interdit les styles en ligne) ; les montants sont en texte à côté.
- Variantes par paramètre (`?m=lfi2025`, `?p=141`) : l'adresse canonique est la page sans paramètre.

## À changer dans les workflows (`.github/`, non modifié ici)

`pages.yml` n'a rien à changer pour fonctionner : `npm run build` lance le prérendu, `npm test` contrôle `dist/` (`web/tests/prerendu.test.ts`). À prévoir :

1. Durée : le build passe d'environ 30 s à 75 s ; `timeout-minutes: 20` suffit.
2. Garder l'ordre `npm run build` puis `npm test` : lancé seul, `npm test` reconstruit et prérend lui-même (plus lent).
3. Copie GitHub Pages : ajouter `env: OVMI_COPIE_SECOURS: "1"` à l'étape `npm run build` de `pages.yml`.
4. Cloudflare : plus rien à exporter, l'adresse vient de `web/adresse-site.json`. Les pages HTML sont déjà servies avec `Cache-Control: public, max-age=0, must-revalidate` (défaut de Workers Static Assets, relevé le 19/11/2026).
5. Facultatif : après le déploiement, vérifier que `sitemap.xml` répond 200 et qu'une adresse inconnue répond 404.

## Vérifications

- `npm test` : `chemins.test.ts` (conversions), `navigation-chemins.test.ts` (reprise par le script, anciens fragments), `prerendu.test.ts` (titre, description et canonique uniques sur toutes les pages, liens tous résolus, CSP, données structurées, plan du site égal aux pages indexables, trois chiffres par commune, nombre de fichiers).
- Chrome sans interface (17/11/2026), site servi sous `/Ou-vont-mes-impots/`, 32 adresses (les 28 routes, 2 départements, 2 communes, variantes à paramètre) en 390 et 1 280 px, clair et sombre, soit 128 passages : 0 erreur de console, 0 requête en échec, 0 requête vers un autre domaine, 0 violation axe-core (WCAG 2.2 AA et bonnes pratiques), 0 débordement horizontal.
- JavaScript désactivé : les 32 pages ont leur titre, leur texte et leurs liens ; parcours accueil, Explorer, budget de l'État suivi par les seuls liens.
- Reprise par le script : clic interne et retour arrière sans rechargement ; `#/explorer/dette`, `#/paie`, `#/etat?m=lfi2025`, `#/local/commune?insee=44109` (vers `/local/44109-nantes/`) redirigés ; calcul complet (2 100 € net, 13 781 € par an, comme dans la recette) puis retour au formulaire prérempli ; choix d'une commune depuis `/local/`.
