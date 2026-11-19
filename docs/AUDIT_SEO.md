# Audit de référencement technique avant lancement (19/11/2026)

Périmètre : site construit (`web/dist`, 2 411 pages prérendues : 59 routes, 101 départements, 2 251 communes) et site en ligne sur l'hôte principal Cloudflare `https://ou-vont-mes-impots.megabigben44.workers.dev/` (copie de secours : GitHub Pages). Base existante : `docs/SEO.md` (prérendu, plan du site, données structurées, 17/11) et `docs/PERF.md`.

## Règle n°0 : ce qui a été réutilisé

| Outil ou ressource | Verdict | Licence | Dernière version relevée | Usage |
|---|---|---|---|---|
| Prérendu maison `web/scripts/prerendre.mjs` (happy-dom + Vite, docs/SEO.md) | réutilisable tel quel | MIT (projet) | commit `3dac12f9` du 19/11/2026 | base de toutes les corrections ci-dessous |
| `web/scripts/og.html` (source de l'image de partage) | réutilisable tel quel | MIT (projet) | idem | rendu au build par le navigateur sans interface |
| Lighthouse (`GoogleChrome/lighthouse`) | réutilisable tel quel, hors dépôt | Apache-2.0 | 13.6.0 (npm, novembre 2026) | mesure mobile sur le site en ligne |
| Google Chrome sans interface (déjà sur le poste et sur les runners GitHub) | réutilisable tel quel | propriétaire, gratuit | installé | capture de `og.html` en PNG 1200 x 630 |
| Protocole sitemaps.org 0.9, schema.org (`WebSite`, `SearchAction`, `Dataset`), Open Graph | réutilisable tel quel | standards ouverts | n/a | formats produits |
| Repli des cartes X/Twitter sur Open Graph (documentation développeurs X) | réutilisable tel quel | n/a | n/a | seule `twitter:card` reste écrite |
| `@vercel/og`, `satori`, `@resvg/resvg-js` (image de partage sans navigateur) | inspiration seulement | MPL-2.0 / MIT | actifs en 2026 | non retenus : une dépendance de plus et des polices TTF à fournir, alors que Chrome est déjà là |

## Constats

| # | Constat (avant correction) | Gravité | Correction |
|---|---|---|---|
| 1 | Sur l'hôte Cloudflare, chaque page déclarait une canonique, une `og:url` et un plan du site pointant vers GitHub Pages ; `robots.txt` annonçait le plan du site de GitHub Pages. Les moteurs auraient indexé la copie de secours plutôt que le site principal. | majeure | adresse publique centralisée dans `web/adresse-site.json` (une ligne), reprise par le prérendu, `index.html` et le code : canonique, Open Graph, plan du site et `robots.txt` désignent l'hôte Cloudflare |
| 2 | Copie de secours GitHub Pages indexable, contenu identique | majeure | la canonique de chaque page de la copie désigne désormais l'hôte Cloudflare (même build) ; en plus, mode `OVMI_COPIE_SECOURS=1` du prérendu : toutes les pages en `noindex, follow`, pas de plan du site (à activer dans `pages.yml`, voir « À faire ») |
| 3 | Adresse « mooneyes.github.io/Ou-vont-mes-impots » écrite sur la carte de partage, dans la référence d'un signalement et dans le pied d'impression | majeure (décision du 19/11 : aucun renvoi vers GitHub ni MoonEyes) | ces trois endroits lisent la constante (`__ADRESSE_SITE__`, `__URL_SITE__`, attribut `data-adresse` de `<main>`) |
| 4 | Image de partage : fichier figé, non régénéré | mineure | `dist/og.png` produit au build depuis `og.html` (Chrome sans interface, 1200 x 630, aucune photo de personne) ; sans navigateur, l'image versionnée reste en place et le bilan l'indique (`prerendu.json`, `image_partage`) |
| 5 | Pas de `SearchAction` alors que la recherche existe (`/recherche/?q=`) | mineure | `WebSite.potentialAction` sur l'accueil |
| 6 | `Dataset` sans identifiant | mineure | `@id` `<site>#donnees` |
| 7 | `twitter:title`, `twitter:description`, `twitter:image` recopiaient Open Graph (environ 400 octets par page) | mineure | retirés : X reprend Open Graph ; `og:image:type` ajouté. Le HTML total passe de 47,7 Mo (avec la nouvelle adresse, plus longue) à 46,2 Mo, sous le budget de 47,5 Mo |
| 8 | Fichiers JSON de `data/` indexables seuls | mineure | `X-Robots-Tag: noindex` sur `/data/*` (`web/public/_headers`) ; les pages qui les citent restent indexées |
| 9 | Titres longs : médiane 82 caractères, 2 378 pages au-delà de 65 (pages commune : « Budget de X (Département) : dépenses, dotations, taux · Où vont mes impôts ») ; descriptions : médiane 213 caractères | mineure (Google tronque l'affichage, pas l'indexation) | corrigé le 19/11/2026 : une seule source `web/src/metadonnees.ts` ; titres de 60 caractères au plus (médiane 57), descriptions de 120 à 155 (médiane 148), uniques et neutres sur toutes les pages, contrôlés par `web/tests/metadonnees.test.ts` (`docs/SEO.md`, « Titres et descriptions ») |
| 10 | Adresses sans barre finale : redirection 307 (temporaire) de Cloudflare vers l'adresse avec barre | mineure | non modifié (`deploy/cloudflare/wrangler.toml`, hors périmètre) ; la canonique et le plan du site portent déjà la bonne forme |
| 11 | Source tierce citée en texte sur `/decisions/resultats/` : `https://github.com/DITP-pilotage/barometre-resultats` (fichiers du baromètre de la DITP) | à décider | gardée : c'est la source officielle d'un producteur public, en texte et sans lien ; le test la tolère nommément et refuse toute autre adresse GitHub |

Vérifiés sans écart : `lang="fr"` sur toutes les pages, pas de `hreflang` (site monolingue, inutile), un seul `<h1>`, une seule canonique, un seul titre, une seule description par page, titres et descriptions uniques (2 411 pages), 3 pages sans contenu propre en `noindex` et hors plan du site, 404 réelle, JSON-LD `WebSite` et `Dataset` sur l'accueil, `BreadcrumbList` sur les autres pages (`WebPage` retiré le 19/11/2026, il répétait les balises de la page).

## Performance et accessibilité vues par les moteurs

Lighthouse 13.6 mobile (lenteur réseau et processeur simulées), site en ligne, 19/11/2026, machine peu chargée (charge 1,7) :

| Page | Performance | Accessibilité | Bonnes pratiques | SEO | LCP | TBT | CLS | Poids |
|---|---|---|---|---|---|---|---|---|
| `/` | 99 | 100 | 100 | 100 | 1,1 s | 140 ms | 0 | 231 Kio |
| `/calcul/` | 100 | 100 | 100 | 100 | 0,9 s | 30 ms | 0 | 201 Kio |
| `/explorer/etat/` | 100 | 100 | 100 | 100 | 1,0 s | 20 ms | 0 | 208 Kio |
| `/local/44109-nantes/` | 99 | 100 | 100 | 100 | 1,0 s | 140 ms | 0 | 433 Kio |

Ressources critiques (build du 19/11, octets bruts / gzip) : feuille de style 49,9 / 10,5 Ko ; script d'entrée 71,6 / 23,5 Ko ; police Figtree 20 Ko et Bricolage Grotesque 77 Ko (préchargées) ; HTML accueil 51,0 / 10,6 Ko, budget de l'État 31,7 / 7,9 Ko, Nantes 18,2 / 5,2 Ko ; image de partage 74 Ko.

Aucun point majeur. Seul signal récurrent : la feuille de style bloque le premier affichage (environ 150 ms estimés) ; l'insérer dans la page est exclu par la CSP (`style-src 'self'`). Piste mineure pour plus tard : un sous-ensemble de la police des titres (77 Ko).

## Où se règle quoi

- Adresse publique : `web/adresse-site.json`, clé `url`. `OVMI_URL_SITE` la remplace le temps d'un build.
- Copie de secours : `OVMI_COPIE_SECOURS=1` au build (noindex partout, pas de `sitemap.xml`).
- Image de partage : `web/scripts/og.html` ; navigateur imposé par `OVMI_CHROME`.
- Contrôles : `web/tests/referencement.test.ts` (plan du site valide et complet par rapport aux routes, une canonique par page, aucune adresse GitHub ni MoonEyes, image 1200 x 630, `SearchAction` et `Dataset`), `web/tests/prerendu.test.ts`, budgets de `web/tests/performance.test.ts` (abaissés le 19/11/2026 après l'allègement du HTML, 46,3 à 39,4 Mo, `docs/PERF.md`), titres et descriptions dans `web/tests/metadonnees.test.ts`.

## À faire hors de ce périmètre

1. Nom de domaine définitif : l'acheter, l'ajouter au Worker (Settings, Domains & Routes), puis changer la ligne `url` de `web/adresse-site.json` et republier. Garder l'adresse `workers.dev` active : les liens déjà partagés continuent de fonctionner, la canonique renvoie au nouveau domaine.
2. Google Search Console et Bing Webmaster Tools : propriété « domaine » (validation DNS), puis déclarer `https://<domaine>/sitemap.xml`. En attendant le domaine : propriété « préfixe d'URL » sur l'adresse `workers.dev`, validée par une balise ou un fichier HTML fourni par Google (à ajouter dans `web/public`).
3. `.github/workflows/pages.yml` : ajouter `env: OVMI_COPIE_SECOURS: "1"` à l'étape `npm run build` de la copie GitHub Pages.
4. `deploy/cloudflare/r2-local.js` (variante R2 seulement) : ajouter `X-Robots-Tag: noindex` aux réponses `/data/local/*`, comme dans `_headers`.
5. Relancer Lighthouse sur le domaine définitif après bascule.
