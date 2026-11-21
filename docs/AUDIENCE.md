# Audience : comptage anonyme des pages vues (côté serveur)

Ajouté le 21/11/2026. Code : `deploy/cloudflare/site.ts` (Worker du site) et `deploy/cloudflare/audience.ts` ; tests : `web/tests/audience.test.ts`.

## Ce qui est compté

Pour chaque page HTML demandée en navigation (GET, réponse 200 en `text/html`), le Worker ajoute 1 à une ligne d'agrégat de la table `visites` de la base D1 `audience` :

| colonne | contenu |
|---|---|
| `jour` | date, heure de Paris (AAAA-MM-JJ) |
| `chemin` | chemin de la page, sans paramètres ni fragment (`/methode/`, `/local/44109-nantes/`), `/autre` si inattendu |
| `pays` | code pays déduit par Cloudflare (`cf.country`), `XX` si inconnu |
| `referent` | nom de domaine du lien d'origine seulement (`google.com`), `aucun` si absent, `interne` si le site lui-même |
| `appareil` | `mobile` ou `ordinateur`, d'après le user-agent |
| `robot` | 1 si user-agent absent ou marqué robot (bot, crawl, spider, curl, wget, python, headless, preview, monitor…) ou sans `Accept-Language`, sinon 0 |
| `vues` | compteur |

Jamais enregistrés : adresse IP, user-agent, ville, heure, URL complète du référent, paramètres d'adresse, cookie, identifiant. Aucun script n'est ajouté à la page, la CSP ne change pas, rien n'est déposé ni lu sur l'appareil.

Non comptés : assets, `/data/`, `sw.js`, requêtes HEAD, redirections et 404, requêtes du service worker et préchargements, et les navigateurs qui envoient `DNT: 1` ou `Sec-GPC: 1` (opposition). L'écriture part en arrière-plan (`ctx.waitUntil`) : une base absente ou en panne ne change rien à la page.

Conservation : 13 mois. Un déclencheur planifié (`[triggers]` de `wrangler.toml`, chaque nuit à 3 h 17 UTC) supprime les lignes plus anciennes.

**Limite à connaître** : faute d'identifiant (c'est voulu), on compte des **pages vues par des humains**, pas des personnes distinctes. Une même personne qui recharge ou revient compte plusieurs fois ; à l'inverse, la navigation à l'intérieur du site par les liens `#/…` ne recharge pas la page et n'est pas comptée. L'heuristique robot laisse passer les robots qui imitent un navigateur.

## Mise en service (pas à pas pour Benjamin)

Tant que ces étapes ne sont pas faites, le Worker sert le site exactement comme avant et ne compte rien.

1. Ouvre https://dash.cloudflare.com/ et le compte qui héberge le Worker `ou-vont-mes-impots`.
2. Menu de gauche : **Stockage et bases de données** > **D1 SQL Database** (en anglais : *Storage & Databases* > *D1 SQL Database*).
3. Clique **Créer une base de données** (*Create Database*).
4. Nom : `audience`. Emplacement : coche **Spécifier la juridiction** et choisis **Union européenne** (*EU*) si l'option est proposée, sinon l'indice d'emplacement **Europe de l'Ouest** (*Western Europe*). Ce choix ne se change plus ensuite. Valide.
5. Sur la page de la base, copie l'**identifiant de la base** (*Database ID*, de la forme `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). Ce n'est pas un secret.
6. Donne cet identifiant à l'agent, ou fais toi-même la modification : dans `deploy/cloudflare/wrangler.toml`, sous le bloc `>>> AUDIENCE`, retire le `# ` au début des 4 lignes `[[d1_databases]]`, `binding`, `database_name`, `database_id`, et remplace `COLLER_ICI_L_IDENTIFIANT_DE_LA_BASE` par l'identifiant. Sur une branche, puis fusion dans `main` (le test `web/tests/audience.test.ts` vérifie la forme de l'identifiant).
7. Workers Builds republie le site au push sur `main`. Si la publication échoue sur un droit D1 : Workers & Pages > `ou-vont-mes-impots` > Paramètres > Builds > jeton API, et ajoute l'autorisation `Compte` / `D1` / `Modifier`.
8. Contrôle : ouvre une ou deux pages du site, puis D1 > `audience` > **Console** et colle `SELECT * FROM visites ORDER BY jour DESC LIMIT 20;`. La table est créée seule au premier passage (schéma aussi dans `deploy/cloudflare/audience.sql`).

## Lire les chiffres (console D1 du tableau de bord)

D1 > `audience` > **Console**, colle une requête, puis **Exécuter**.

1. Pages vues par des humains, par jour, sur 30 jours :

```sql
SELECT jour, SUM(vues) AS pages_vues_humains
FROM visites
WHERE robot = 0 AND jour >= date('now', '-30 days')
GROUP BY jour
ORDER BY jour DESC;
```

2. Pages les plus vues par des humains (30 jours) :

```sql
SELECT chemin, SUM(vues) AS vues
FROM visites
WHERE robot = 0 AND jour >= date('now', '-30 days')
GROUP BY chemin
ORDER BY vues DESC
LIMIT 30;
```

3. Provenance par domaine (humains, 30 jours ; `aucun` = adresse tapée, favori ou lien sans référent) :

```sql
SELECT referent, SUM(vues) AS vues
FROM visites
WHERE robot = 0 AND jour >= date('now', '-30 days')
GROUP BY referent
ORDER BY vues DESC
LIMIT 30;
```

4. Part des pages vues sur téléphone (humains, 30 jours) :

```sql
SELECT ROUND(100.0 * SUM(CASE WHEN appareil = 'mobile' THEN vues ELSE 0 END) / SUM(vues), 1) AS part_mobile_pct,
       SUM(vues) AS pages_vues_humains
FROM visites
WHERE robot = 0 AND jour >= date('now', '-30 days');
```

Pour voir le poids des robots : remplace `robot = 0` par `robot = 1` dans la requête 1.

## Cadre CNIL (relevé du 21/11/2026)

- Le dispositif ne lit ni n'écrit rien sur l'appareil (ni cookie, ni stockage local, ni script, ni empreinte) : il traite seulement, côté serveur, les en-têtes que tout navigateur envoie avec chaque requête, réduits aussitôt à des catégories.
- Même lu au plus strict comme un traceur de mesure d'audience, il remplit les conditions d'exemption de consentement des lignes directrices de la CNIL (délibération n° 2020-091 du 17/09/2020, points 50 à 52) : finalité limitée à la mesure d'audience pour le compte exclusif de l'éditeur, statistiques anonymes seulement, aucun recoupement, aucune transmission à des tiers, aucun suivi de la navigation. Sources : https://www.cnil.fr/fr/cookies-solutions-pour-les-outils-de-mesure-daudience (04/07/2025) et https://www.cnil.fr/sites/cnil/files/atoms/files/lignes_directrices_de_la_cnil_sur_les_cookies_et_autres_traceurs.pdf.
- Grille d'auto-évaluation CNIL (juillet 2025, https://cnil.fr/sites/default/files/2025-07/outil_d_auto-evaluation_mesure_d_audience.pdf) : localisation au plus à la ville (ici le pays), données du navigateur minimisées (ici mobile ou ordinateur), aucun identifiant ; opposition possible (ici `Do Not Track` ou `Global Privacy Control`, sans cookie). Conservation 13 mois, sous le maximum de 25 mois recommandé. Information : mentions légales, section « Confidentialité des visiteurs ».

## Existant évalué (règle n° 0, 21/11/2026)

| Outil | Verdict | Licence | Dernier commit | Pourquoi |
|---|---|---|---|---|
| Cloudflare D1 | réutilisable tel quel | service (offre gratuite) | n/a | lisible dans la console du tableau de bord, upsert SQLite |
| Workers Analytics Engine | à adapter, non retenu | service | n/a | lecture seulement par API SQL avec jeton, pas de console ; conservation 3 mois |
| Cloudflare Web Analytics | écarté | service | n/a | balise JavaScript chargée depuis `static.cloudflareinsights.com` : contraire à la CSP et à la promesse du site |
| benvinegar/counterscale | inspiration seulement | MIT | 04/10/2026 | script côté client et visiteurs uniques par cache du navigateur |
| wpgaurav/gt-analytics (dérivé de counterscale) | inspiration seulement | MIT | 12/09/2026 | même principe, côté client |
| gdsc-bme/flarelytics | écarté | GPL-3.0 | 26/12/2023 | abandonné, côté client |
