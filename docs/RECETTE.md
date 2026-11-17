# Recette avant diffusion (17/11/2026)

Périmètre : site `web/` (Vite + TypeScript), version construite localement depuis le dépôt et servie compressée (gzip) sous `/Ou-vont-mes-impots/`, comme sur GitHub Pages. Les mesures « avant » portent sur la construction du code au début de la recette, les mesures « après » sur la construction finale.

Méthode d'accessibilité : skill `design:accessibility-review` (référentiel WCAG, contrôles contraste, clavier, lecteur d'écran, zoom), appliquée avec le RGAA 4.1 et WCAG 2.2 AA.

Outils (installés hors du dépôt, dans un dossier de recette) : axe-core 4 via puppeteer-core et Chrome, Lighthouse 13 (mobile, 4G simulée, CPU x4), scripts puppeteer pour le clavier, le reflow, les cibles et les parcours, curl pour les liens externes. pa11y a été installé mais n'apporte rien de plus qu'axe-core (même moteur), il n'a pas été retenu dans les résultats.

## Synthèse

| | Avant | Après |
|---|---|---|
| axe-core, 29 écrans x 390/1280 px x clair/sombre (116 passages) | 14 violations (7 écrans en 390 px, 2 thèmes) + 1 débordement horizontal | 0 |
| Reflow 320 px et zoom 200 % | 3 écrans débordent (509, 370, 337 px) | 0 |
| Lighthouse performance, accueil / calcul / explorer / État | 84 / 84 / 83 / 83 | 100 / 100 / 100 / 100 |
| Lighthouse performance, commune 62041 / Paris | 57 / 81 | 83 / 99 |
| Lighthouse performance, vie politique / contrôle | 85 / 81 | 100 / 97 |
| Lighthouse accessibilité (toutes les pages mesurées) | 100 | 100 |
| CLS (toutes les pages) | 0,31 à 0,35 | 0 à 0,009 |
| LCP commune Nantes / Bordeaux / Arras (62) | 3,9 s / 5,1 s / 6,3 s | 1,8 s / 2,0 s / 4,7 s |
| Passage saisie vers résultat : TBT / CLS | 2 000 ms / 0,306 | 100 ms / 0,021 |
| Liens internes explorés (fragments) | 452, 0 mort, 0 page en erreur, 0 page sans sortie | idem |
| Liens vides (`href=""`) | 13 occurrences sur les pages Votes | 0 |

Constats : 19 au total, 2 bloquants, 8 importants, 9 mineurs. Corrigés : 2 bloquants (dont un à compléter par l'éditeur), 8 importants (un en partie, le reste relève du pipeline), 4 mineurs.

## Constats bloquants

### B1. Salaire au format français lu de travers, sans message (corrigé)

Preuve : sur un navigateur réglé en anglais, saisir « 2100,50 » dans le champ (type `number`) donnait 210 050 € (message « trop élevé ») ; « 1500,5 » aurait donné 15 005 € et un résultat faux, sans erreur. Les espaces (« 2 100 ») étaient aussi refusés.

Correction : champs montant et quotité en `type="text"` avec `inputmode="decimal"` (clavier numérique conservé sur mobile) et lecture explicite (`web/src/ecrans/saisie.ts`, fonction `nombre`) : espaces, espaces insécables, virgule, point et « € » final acceptés ; toute autre saisie est refusée sur le champ. Test : `web/tests/recette.test.ts`, « montant au format français » et « texte illisible refusé ».

### B2. Information RGPD des élus et candidats absente (constat I4 de `docs/AUDIT_SECURITE.md`) (corrigé, à compléter)

Preuve : la page Mentions ne traitait que des visiteurs ; elle affirmait aussi que l'éditeur avait communiqué son identité à l'hébergeur, ce que rien dans le dépôt ne permet de vérifier.

Correction (`web/src/ecrans/mentions.ts`) : section « Données personnelles des élus et candidats » avec personnes et données concernées, finalité, base légale (intérêt légitime, art. 6.1.f RGPD ; données dont la publication est prévue par la loi : JO, CNCCFP, données ouvertes du Parlement ; art. L. 322-2 CRPA), sources et dates lues dans les données (`vie_politique/annees.json`, `decisions/index.json`), durée de conservation (tant que la source publie, avec durée à fixer), hébergement aux États-Unis, droits (accès, rectification, effacement, limitation, opposition art. 21), délai d'un mois, réclamation CNIL. L'obligation LCEN d'identification auprès de l'hébergeur est rappelée comme une condition, sans l'affirmer. Aucune identité, adresse ni e-mail inventés : trois emplacements `[À COMPLÉTER PAR L’ÉDITEUR]` (identité et contact privé, durée retenue, canal privé de demande). Lexique neutre vérifié par le test existant. Test : « mentions : information RGPD ».

Reste : bloquant tant que les trois emplacements ne sont pas remplis (voir « À faire par l'éditeur »).

## Constats importants

| N° | Constat | Critère | Preuve | Statut |
|---|---|---|---|---|
| I1 | Tableaux défilants inaccessibles au clavier | WCAG 2.1.1, RGAA 7.3 | axe `scrollable-region-focusable` sur `/explorer/ue`, `/explorer/recettes`, `/explorer/niches`, `/local/commune`, `/beneficiaires`, `/decisions/controle`, `/methode` (390 px, clair et sombre) | Corrigé : `rendreDefilables` (`web/src/util.ts`) donne `tabindex="0"`, `role="region"` et un nom tiré de la légende ; un observateur (`web/src/main.ts`) traite aussi les tableaux insérés après coup (fiches dépliées, pagination des candidats) ; focus visible en CSS |
| I2 | Débordement horizontal à 320 px et à 200 % | WCAG 1.4.10, RGAA 10.11 | `/explorer/operateurs` 509 px, `/decisions/controle` 370 px, `/methode` 337 px : libellés de source sans espace (`p.source`) | Corrigé : `overflow-wrap` sur `body` et `.source` |
| I3 | Décalage de mise en page à chaque chargement (CLS 0,31 à 0,35) | Core Web Vitals | Lighthouse `layout-shifts` : le pied de page apparaît sous l'en-tête pendant « Chargement… » puis est repoussé | Corrigé : `main { min-height: 100vh }`, retour en haut avant de vider l'écran lors d'une navigation interne (`web/src/routeur.ts`) |
| I4 | Page commune lente (LCP 6,3 s pour le 62, 5,1 s Bordeaux) | LCP < 2,5 s | 1 Mo transféré pour une commune du 62, dont 459 Ko de budgets du département | En partie : rendu progressif (titre, population, liens dès la géographie ; budgets, puis dotations, taux, subventions) ; LCP 1,8 s Nantes, 2,0 s Bordeaux, 2,1 s Paris, 4,7 s Arras. Le reste demande un découpage des fichiers par le pipeline : `docs/PERF.md` |
| I5 | Calcul bloquant 2 s sur mobile | INP, TBT | Lighthouse (timespan saisie vers résultat) : TBT 2 000 ms, une tâche longue de 1 982 ms | Corrigé : moteur publicodes dans un Web Worker (`web/src/calcul/moteur-travailleur.ts`, `hors-fil.ts`), repli sur le fil principal si le worker est refusé ; fonctions légères sorties dans `calcul/agregats.ts`. TBT 100 ms |
| I6 | Identifiant technique affiché | RGAA 8.5 (compréhension), lisibilité | « autres_taxes_produits (Plusieurs administrations) » dans « Sur 100 € par destinataire », 5 profils sur 5 | Corrigé : libellé « Plusieurs bénéficiaires (répartition non sourcée) » (`calcul/destinataires.ts`) |
| I7 | Liens vides qui rechargent la page | RGAA 6.2 | 13 occurrences de `href=""` sur `/decisions/votes` (amendements ou mouvements sans adresse dans les données) | Corrigé : texte sans lien quand l'adresse manque (`ecrans/votes.ts`) ; test « aucun lien vide » |
| I8 | Feuille « Plus » ouverte derrière le focus | WCAG 2.4.11 | Après ouverture, Tab sort de la feuille, `aria-expanded` reste `true` et la feuille (barre du bas, mobile) masque la page | Corrigé : fermeture quand le focus sort de la navigation ; Échap et retour du focus sur « Plus » déjà en place |

## Constats mineurs

| N° | Constat | Statut |
|---|---|---|
| m1 | Message « hors V1 » ou erreur générale : le focus restait sur le bouton (paragraphe non focalisable) | Corrigé (`tabindex="-1"` et focus sur le message) |
| m2 | Garde alternée supérieure au nombre d'enfants ramenée sans le dire | Corrigé : message sur le champ |
| m3 | Liens de la liste des programmes (Réalisations) hauts de 26 px | Corrigé : 45 px |
| m4 | Dernier lien du fil d'Ariane étroit (36 à 39 px de large, 44 px de haut) | Conforme AA (2.5.8, 24 px), non corrigé |
| m5 | Cases à cocher et boutons radio de 22 px | Conforme : le libellé entier est cliquable (44 à 53 px de haut) |
| m6 | `robots.txt` absent à la racine `mooneyes.github.io` (SEO Lighthouse 92) | Hors `web/` : dépôt `mooneyes.github.io` à créer si voulu |
| m7 | Adresses de sources mortes ou malformées dans `niches/index.json` (non cliquables sur le site) | Pipeline : voir « Liens externes » |
| m8 | `destinataire()` affiche l'identifiant si un destinataire inconnu arrive des données | Cas connu corrigé ; repli générique conservé |
| m9 | Léger décalage au chargement des polices (0,006) | Accepté |

## Contrôles manuels

- Clavier : lien d'évitement, marque, 4 rubriques et « Plus » dans l'ordre, puis le contenu ; focus visible partout (contour 3 px, aucun élément sans indicateur sur l'accueil, le calcul, l'État, Chez moi) ; feuille « Plus » : Entrée ouvre et place le focus sur le premier lien, Échap ferme et rend le focus. Formulaire de calcul entièrement utilisable au clavier ; filtres et listes (opérateurs, programmes) atteignables.
- Sankey : dessiné seulement sur écran large, `role="img"` et nom qui renvoie à la liste ; la même information est donnée en liste de liens (alternative complète au clavier et au lecteur d'écran).
- Lecteur d'écran (contrôle par l'arbre d'accessibilité, pas avec NVDA ou VoiceOver) : à chaque changement de page, titre du document mis à jour, focus sur le `h1`, annonce dans la zone `aria-live` (« Explorer les dépenses publiques ») ; tableaux avec `caption` et `th scope` ; erreurs de saisie liées au champ (`aria-describedby`, `aria-invalid`) et focus sur le champ fautif.
- Zoom 200 % (640 px CSS) et 320 px : aucun débordement après correction, sur 26 écrans.
- `prefers-reduced-motion: reduce` : aucune transition ni animation active, Sankey sans animation.
- Cibles : boutons et liens de navigation de 44 à 56 px ; voir m3 à m5.
- Contrastes : test existant `contrastes.test.ts` vert, axe sans violation de contraste en clair et en sombre.

## Parcours réels (390 px, Chrome)

| Profil | Total annuel versé | Impôt sur le revenu | Contrôles |
|---|---|---|---|
| SMIC, 1 426 € net | 9 338 € | 0 € | Cohérent (sous le seuil, décote) |
| 2 100 € net | 13 781 € | 1 004 € | Égal au cas type OpenFisca C04 |
| 4 000 € net, cadre | 27 668 € | 6 530 € | APEC et CET présents, tranche 30 % |
| Couple marié, 2 enfants, 2 100 + 1 800 € | 24 144 € | 0 € | 3 parts ; impôt brut d'environ 980 € annulé par la décote |
| Temps partiel 80 %, 1 150 € net | 8 069 € | 0 € | Équivalent temps plein 1 437 € : pas d'alerte SMIC (alerte bien affichée pour 1 150 € à temps plein) |

- Erreurs de saisie : champ vide, 0, négatif, 9 999 999, quotité 0 ou 150, conjoint sans salaire, garde alternée incohérente, outre-mer et fonctionnaire (hors V1) : message clair, champ marqué invalide, focus sur le champ ou le message.
- Retour arrière depuis le résultat : formulaire prérempli (salaire, temps partiel, quotité) ; avance : résultat de nouveau affiché. Résultat ouvert sans saisie (rechargement) : renvoi vers la saisie avec explication.
- Partage de carte : sans `navigator.share`, image PNG téléchargée (`ou-vont-mes-impots.png`) et message « Image téléchargée sur ton appareil. » ; aucune donnée dans l'adresse.
- « Voir aussi » et fil d'Ariane présents sur toutes les pages de rayon ; aucune page sans lien de sortie dans le contenu.
- Aucune erreur JavaScript en console sur l'ensemble des parcours.

## Liens

Internes : 452 adresses explorées depuis l'accueil (au plus 12 variantes de paramètres par écran) : aucun chemin inconnu, aucune page en erreur.

Externes affichés sur le site : 214 adresses distinctes, vérifiées une par une (HEAD, puis GET si refus), sans contourner les refus :

- 195 répondent 200 (dont 1 seulement en GET : `assemblee-nationale.fr/dyn/17/amendements/AMANR5L17PO59048B3210P2D1N002701`).
- 18 Légifrance (`legifrance.gouv.fr/jorf/id/JORFTEXT…`, pages Votes) répondent 403 à un client automatique : non vérifiables ainsi, à contrôler dans un navigateur. Exemple : `JORFTEXT000055023963`, `JORFTEXT000054826958`, `JORFTEXT000049282811`.
- Aucun lien mort confirmé.

Adresses présentes dans les données (6 618 distinctes, pour l'essentiel des amendements et des rapports) : échantillon de 217 (toutes les adresses hors Assemblée, Sénat, Cour des comptes et Légifrance, plus 40 tirées au hasard pour chacun de ces quatre sites) :

- 152 répondent 200.
- 56 refus 403 : 39 Légifrance (anti-robot) et 17 dépôts GitHub tiers (`controle/index.json`, recherche publique) refusés par le proxy de l'environnement de recette ; non vérifiables ici.
- 1 refus 429 (trop de requêtes) : `commission.europa.eu/document/download/45d0623a-…` ; non réessayé.
- 404 : `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data` et `kohesio.ec.europa.eu/api/facet/eu/search/projects` (bases d'API, pas des pages : normal) ; `budget.gouv.fr/documentation/documents-budgetaires-lois` (404 puis 200 au second essai : intermittent).
- Sans réponse depuis l'environnement : `www.performance-publique.budget.gouv.fr/` (site fermé, à remplacer par budget.gouv.fr), `fipeco.fr/pdf/Niches2023.pdf`, `data.economie.gouv.fr/explore/dataset/impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir/` (connexion coupée, à revérifier dans un navigateur).
- Adresse malformée : `https://www.enseignementsup-recherche.gouv.fr/ (bilans du CIR)` (texte collé à l'adresse) dans `niches/index.json`.

Ces adresses de données ne sont pas cliquables sur le site ; leur correction relève du pipeline.

## Corrections faites (fichiers)

- `web/src/ecrans/mentions.ts` : B2.
- `web/src/ecrans/saisie.ts` : B1, m1, m2 ; enregistrement des destinataires sur le fil principal.
- `web/src/calcul/agregats.ts` (nouveau), `moteur-travailleur.ts` (nouveau), `hors-fil.ts` (nouveau), `moteur.ts`, `hors-bulletin.ts`, `ecrans/paie.ts`, `web/vite.config.ts` (`worker.format`) : I5.
- `web/src/calcul/destinataires.ts` : I6.
- `web/src/ecrans/commune.ts`, `web/src/routeur.ts` (écrans à rendu progressif : `{ suite }`, retour en haut) : I3, I4.
- `web/src/util.ts`, `web/src/main.ts` : I1, I8.
- `web/src/ecrans/votes.ts` : I7.
- `web/src/styles.css` : I1 (focus), I2, I3, m3, mise en forme des mentions.
- `web/tests/recette.test.ts` (nouveau, 8 tests) ; suite complète : 127 tests verts, construction OK.
- `docs/PERF.md` : découpages proposés au pipeline.

## À faire par l'éditeur

1. Remplir les trois emplacements `[À COMPLÉTER PAR L’ÉDITEUR]` de la page Mentions (identité ou dénomination, canal de contact privé, durée de conservation) et vérifier auprès de GitHub que les éléments d'identification LCEN ont bien été communiqués. Option sans e-mail personnel : activer « Private vulnerability reporting » ou une adresse dédiée.
2. Faire valider la base légale (intérêt légitime) et la durée de conservation, puis fermer le constat I4 de `docs/AUDIT_SECURITE.md`.
3. Test avec un vrai lecteur d'écran (NVDA sous Windows, VoiceOver sur iPhone) sur le parcours calcul puis résultat : non faisable dans l'environnement de recette.
4. Ouvrir dans un navigateur 3 ou 4 liens Légifrance des pages Votes (refus 403 aux robots).
5. Pipeline : découpages de `docs/PERF.md` (page commune des grands départements, candidats) et adresses de sources de `niches/index.json`.
6. Pousser le commit de recette (non poussé) puis relancer Lighthouse sur l'adresse publique.
