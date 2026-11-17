# Déploiement : Cloudflare (site) et VPS OVH (collecte)

Aujourd'hui le site est publié sur GitHub Pages (`.github/workflows/pages.yml`). Ce document prépare le passage sur Cloudflare et décrit le VPS OVH de collecte. Rien ici ne contient d'identifiant réel : comptes, jetons et clés vivent dans des variables d'environnement, des secrets GitHub ou `/etc/ovmi/*.env`.

## 1. Outils existants évalués (relevé du 17/11/2026)

| Outil | Verdict | Licence | Dernier commit | Usage ici |
|---|---|---|---|---|
| `wrangler` (CLI officielle, dépôt `cloudflare/workers-sdk`) | réutilisable tel quel | MIT ou Apache-2.0 | 17/11/2026 | publication, figée en 4.164.0 par `deploy/cloudflare/package-lock.json` (empreintes npm) |
| Workers Static Assets (`[assets]` de wrangler) | réutilisable tel quel | service | n/a | hébergement retenu : `_headers`, `_redirects`, brotli en bordure |
| `cloudflare/wrangler-action` v4.1.3 (`953926a2e2182532811c01a25e53647d93bf07c0`) | à adapter, non retenu | MIT ou Apache-2.0 | 24/09/2026 | installe wrangler sans fichier de verrouillage ; `publier.sh` fait la même chose avec versions figées et contrôle des limites |
| Cloudflare Pages (`wrangler pages deploy`) | inspiration seulement | service | n/a | mêmes limites, mais Cloudflare réserve les nouveautés à Workers ; pas de R2 sur la même origine sans Functions |
| `cloudflare/pages-action` | écarté | n/a | dépôt inaccessible (retiré) | remplacé par wrangler |
| rclone (déjà sur le VPS) | réutilisable tel quel | MIT | n/a | envoi de `data/local` vers R2 dans la variante R2 (`envoyer-r2.sh`) |

## 2. Le site tient-il dans les limites Cloudflare ?

Limites (offre gratuite, Workers comme Pages) : 20 000 fichiers par version (100 000 en offre payante), 25 Mio par fichier, 100 règles `_headers`, 2 000 redirections statiques.

Mesure du 17/11/2026 sur `web/dist` (après `npm run build`) :

| | Valeur | Limite | Marge |
|---|---|---|---|
| fichiers | 4 226 (dont 4 174 JSON de données) | 20 000 | 21 % utilisés |
| entrées comptées par wrangler (fichiers + 1 308 dossiers) | 5 534 | 20 000 | 28 % |
| plus gros fichier | `data/controle/lobbying/organisations.json`, 3,3 Mio | 25 Mio | x 7,6 |
| volume total | 218 Mio (dont `data/local` 166 Mo, 2 320 fichiers) | aucune | |
| règles `_headers` | 8 | 100 | |

Conclusion : **compatible sans R2**. `publier.sh` refait ce contrôle à chaque publication (échec au-delà du plafond ou de 25 Mio, avertissement au-delà de 80 %).

### Plan R2 (prêt, à activer seulement si un seuil saute)

Déclencheur : `publier.sh` avertit (plus de 16 000 entrées) ou refuse (plus de 20 000, ou un fichier de plus de 25 Mio). Le risque réel est `data/local/decisions/` (un fichier par collectivité et par année).

1. Créer un bucket R2 `ovmi-donnees-local` (tableau de bord > R2), sans accès public.
2. Créer un jeton R2 « Object Read & Write » limité à ce bucket ; renseigner `RCLONE_CONFIG_R2_*` (voir l'en-tête de `deploy/cloudflare/envoyer-r2.sh`).
3. `deploy/cloudflare/envoyer-r2.sh --simuler`, puis sans `--simuler`.
4. `deploy/cloudflare/publier.sh --r2` : `data/local` est exclu des fichiers statiques (`.assetsignore`) et servi par `r2-local.js` sur la **même origine**, donc la CSP (`connect-src 'self'`) ne change pas. Le Worker ne tourne que pour `/data/local/*` (`run_worker_first`), répond en lecture seule (GET, HEAD), gère `ETag` et `304`, refuse toute clé hors `local/*.json`, et pose lui-même les en-têtes de sécurité et de cache.

Testé en local (`wrangler dev`) : 200 avec CSP et cache, 304 sur `If-None-Match`, 404 sur clé absente ou `..`, 405 sur POST. Offre gratuite : 100 000 requêtes Worker par jour pour `/data/local/*` seulement.

Si un fichier unique dépasse 25 Mio, la bonne correction est dans le pipeline (découper par année ou par département), pas côté hébergement.

### En-têtes, cache, compression

- `deploy/cloudflare/_headers` : CSP **identique** à la balise `<meta>` de `web/index.html`, plus `frame-ancestors 'none'` (sans effet dans une balise meta). Aussi `Referrer-Policy: no-referrer`, `nosniff`, `X-Frame-Options: DENY`, COOP et CORP `same-origin`, `Permissions-Policy` restrictive, HSTS un an (sans `includeSubDomains` : ne pas engager les autres sous-domaines du domaine personnel).
- Cache : `index.html` revalidé à chaque visite ; `/assets/*` (noms à empreinte Vite) un an `immutable` ; `/data/*` une heure puis `stale-while-revalidate` un jour (données hebdomadaires, noms stables).
- Compression : brotli et gzip faits par Cloudflare en bordure pour le JSON, rien à précompresser (vérifié : `Content-Encoding: br` en local).
- `deploy/cloudflare/_redirects` : `/Ou-vont-mes-impots/*` vers `/:splat` (301), pour les liens copiés depuis l'ancienne adresse GitHub Pages.
- Le site route par fragment (`#/…`) : `not_found_handling = "none"`, une adresse inconnue donne une vraie 404.

Tout cela a été vérifié avec `wrangler dev` (en-têtes présents, `_headers` non servi, redirection 301, 404).

## 3. Mise en place sur Cloudflare (pas à pas pour Benjamin)

Choix retenu : **Workers Static Assets**, publié par `deploy/cloudflare/publier.sh` (wrangler figé), sans action GitHub tierce.

1. **Compte** : créer un compte Cloudflare (offre gratuite suffit). Noter l'identifiant de compte (tableau de bord, colonne de droite de « Workers & Pages » ou de la page d'accueil du compte).
2. **Jeton API à droits minimaux** : Mon profil > Jetons API > Créer un jeton > Modèle personnalisé :
   - Autorisations : `Compte` / `Workers Scripts` / `Modifier`. Rien d'autre.
   - Ressources du compte : inclure **ce seul compte**.
   - Facultatif : filtrage IP (adresse du VPS si la publication part de là), date d'expiration (un an).
   - Si wrangler refuse faute de droit de lecture du compte, ajouter `Compte` / `Paramètres du compte` / `Lire`, et seulement cela.
3. **Premier essai depuis un poste** (Node 20.19 ou plus) :
   ```bash
   cd web && npm ci && npm run build && cd ..
   deploy/cloudflare/publier.sh --verifier                    # contrôles + simulation, sans identifiant
   export CLOUDFLARE_ACCOUNT_ID=…  CLOUDFLARE_API_TOKEN=…      # dans le terminal, jamais dans un fichier versionné
   deploy/cloudflare/publier.sh
   ```
   Le Worker `ou-vont-mes-impots` est créé au premier envoi ; l'adresse `https://ou-vont-mes-impots.<sous-domaine>.workers.dev` s'affiche (le sous-domaine `workers.dev` est choisi une fois, à la première visite de « Workers & Pages »).
4. **Vérifier** : `curl -sI https://<adresse>/ | grep -i -e content-security -e cache-control` puis ouvrir le site (simulateur, écran Ta commune).
5. **Domaine personnalisé (facultatif)** : le domaine doit utiliser les DNS de Cloudflare (ajouter le site au compte, changer les serveurs DNS chez le registraire, par exemple OVH). Puis Workers & Pages > `ou-vont-mes-impots` > Paramètres > Domaines et routes > Ajouter > Domaine personnalisé. Le certificat est automatique. Le jeton n'a besoin d'aucun droit de zone, puisque le domaine est attaché depuis le tableau de bord. Dans SSL/TLS, activer « Toujours utiliser HTTPS ».
6. **Secrets GitHub** (pour la publication automatique) : Settings > Environments > New environment `cloudflare`, limité à la branche `main`, avec les secrets `CLOUDFLARE_API_TOKEN` et `CLOUDFLARE_ACCOUNT_ID` ; Settings > Variables > `OVMI_CLOUDFLARE` = `1` pour activer le job ci-dessous.
7. **Bascule** : quand l'adresse Cloudflare est validée, mettre à jour `<link rel="canonical">` et `og:url` de `web/index.html` (aujourd'hui `mooneyes.github.io`), puis désactiver GitHub Pages (Settings > Pages) ou y laisser une page qui renvoie vers la nouvelle adresse (GitHub Pages ne sait pas faire de redirection HTTP).

### Changement de workflow proposé (à appliquer par le responsable de `.github/workflows`)

Dans `pages.yml`, le job `construire` livre `web/dist` en artifact, et un job `cloudflare` séparé, seul à voir les secrets Cloudflare, publie sans relancer `npm ci` de `web/` (le code tiers du site ne côtoie jamais le jeton) :

```yaml
  construire:
    steps:
      # … étapes actuelles, après « npm test » :
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        if: vars.OVMI_CLOUDFLARE == '1'
        with:
          name: site
          path: web/dist
          retention-days: 3

  cloudflare:
    needs: construire
    if: vars.OVMI_CLOUDFLARE == '1'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    environment:
      name: cloudflare
    concurrency:
      group: cloudflare
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: main
          persist-credentials: false
          sparse-checkout: deploy/cloudflare
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: 22
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          name: site
          path: web/dist
      - run: deploy/cloudflare/publier.sh
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

Les jobs GitHub Pages actuels peuvent rester en parallèle pendant la transition, puis être retirés. Pour garder `deploy/cloudflare/package-lock.json` à jour, ajouter à `.github/dependabot.yml` une entrée `package-ecosystem: npm`, `directory: /deploy/cloudflare`.

## 4. VPS OVH de collecte

Installation et stockage : `docs/STOCKAGE.md`. Changements du 17/11/2026 :

- **Constat I5 (docs/AUDIT_SECURITE.md) fermé côté code** : `ovmi-collecte.service` retire `OVMI_ALERTE_GITHUB_JETON` de son environnement (`UnsetEnvironment=`, appliqué après `EnvironmentFile=`), même si une ancienne installation l'a laissé dans `stockage.env` ; `env.exemple` ne contient plus ces lignes ; `installer_vps.sh` signale un jeton resté dans `stockage.env` sans le lire ni le déplacer. Symétriquement, l'alerte ne reçoit plus les clés S3. **Reste manuel** : déplacer le jeton vers `/etc/ovmi/alerte.env` puis vider la ligne dans `stockage.env` (le fichier reste lisible par le groupe `ovmi`).
- **Orchestrateur** : avec `OVMI_PIPELINE=1` dans `stockage.env`, `collecte-hebdo.sh` lance après la collecte `pipeline/tout.py entrepot --plafond-go 10` puis `pipeline/tout.py --budget 18000` (sauté proprement si `tout.py` est absent de la version déployée). Code de sortie 4 si l'orchestrateur échoue. Les sorties restent sur le VPS : la publication passe toujours par GitHub (`data.yml` valide et committe), le VPS n'a aucun droit d'écriture sur le dépôt ni sur Cloudflare. `installer_vps.sh` installe `poppler-utils` et `tesseract-ocr(-fra)` comme `data.yml`.
- **Dépendances** : `installer_vps.sh` installe `requirements.lock` avec `--require-hashes` (mêmes versions que la production de `site/data`) quand le VPS est en CPython 3.13 x86_64, sinon repli signalé sur `requirements.txt`.
- **Durcissement systemd** : en plus du confinement existant, `ProtectProc=invisible`, `RemoveIPC=yes`, `SystemCallArchitectures=native`, `SystemCallFilter=@system-service` (appel interdit : erreur EPERM, pas d'arrêt brutal), limite de débit de journal. Exposition `systemd-analyze security` : 3,2 vers 1,8 pour les deux services. `installer_vps.sh` refuse d'activer des unités que `systemd-analyze verify` rejette.
- **Rotation des journaux** : `/var/lib/ovmi/journaux/collecte-*.log` compressés (gzip) dès le lendemain, 12 gardés (`OVMI_JOURNAUX_GARDES`) ; journald reste réglé par le système (VPS partagé, pas de changement global).
- `shellcheck` : aucun avertissement sur `deploy/*.sh` et `deploy/cloudflare/*.sh`.

À faire sur le VPS après mise à jour du dépôt : `sudo bash /var/lib/ovmi/ou-vont-mes-impots/deploy/installer_vps.sh` (relançable, ne touche pas aux clés), puis traiter l'éventuel avertissement I5.
