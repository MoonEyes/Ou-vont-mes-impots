# Audit du parcours principal (19/11/2026)

Parcours suivi par la plupart des visiteurs : accueil, saisie du salaire (`/calcul`, `/calcul/bulletin`), résultat (`/calcul/resultat`), puis où va chaque euro (`/suivre-un-euro`, `/explorer/etat`, détail et Sankey `/explorer/etat/detail`). Direction visuelle « billet découpé » inchangée : mêmes polices, couleurs, formes et composants ; seules des tailles et l'ordre de quelques blocs changent sur téléphone.

## Méthode de mesure

- Site construit (`vite build`), servi compressé (gzip niveau 9, comme l'hébergeur), sans service worker ; Chrome piloté par Playwright.
- Deux écrans : téléphone 360 x 640 px et ordinateur 1 280 x 800 px. Mode lent : 4G simulée (150 ms, 1,6 Mbit/s) et processeur ralenti x4, frappe du salaire à une touche par demi-seconde.
- « Avant » : `origin/main` au commit 3dac12f9, construit et mesuré dans les mêmes conditions. Positions en pixels depuis le haut de la page (bas de l'écran du téléphone : 640).
- Poids : octets transférés par étape (fichiers compressés), et modules JS mesurés dans `dist/assets` (gzip 9).
- Accessibilité : contrôle par script dans Chrome (identifiants en double, champs sans libellé, sauts de niveaux de titres, cibles de moins de 24 px, débordement horizontal à 360 px), lecture du code (focus, ordre de lecture, alternatives textuelles, annonces), et tests existants (`contrastes.test.ts`, `ecrans.test.ts`).

## Constat

### Clics et écrans jusqu'au premier « où va mon argent »

- Accueil : 1 champ (salaire), 1 bouton. Le bouton ouvre `/calcul`, qui lance le calcul tout seul puis affiche le résultat : 1 clic, 2 écrans (dont un écran de passage), 7 tabulations depuis le haut de page jusqu'au champ.
- Le résultat montre la répartition « sur 100 € » ; chaque part du billet mène à sa caisse (Sécurité sociale, État, collectivités) : 2 clics jusqu'au premier détail.
- Le bouton principal du résultat, « Suivre mes euros », menait au budget de l'État dans son ensemble, quelle que soit la plus grande part de ce que verse la personne (pour un salarié, la Sécurité sociale) ; les lignes « ligne par ligne » ne menaient nulle part.

### Poids et temps (360 px)

| Étape | Transféré | Dont JS de l'écran | Dont données |
|---|---|---|---|
| Accueil | 210 Ko (29 requêtes, dont 95 Ko de polices et 27 Ko de glossaire des sigles) | 11 Ko | 30 Ko (tuiles des caisses) |
| Calcul et résultat | 50 Ko, plus le moteur de calcul (Web Worker, 161 Ko) | 22 Ko | 15 Ko (affectation, TVA) |
| Budget de l'État | 30 Ko | 5 Ko | 24 Ko, tout attendu avant affichage |
| Suivre un euro | 15 Ko | 9 Ko | 6 Ko |
| Fiche de paie | 12 Ko | 11 Ko | en cache |

- Le moteur de calcul (161 Ko compressés) n'était demandé qu'après le clic sur « Découper mon billet » : il se téléchargeait pendant que la personne attendait son résultat.
- Le budget de l'État attendait `millesimes/index.json` (7 Ko) et `tracabilite/resume.json` (15 Ko), qui ne servent qu'à deux encadrés en bas de page, avant d'afficher quoi que ce soit.
- Le Sankey (ECharts, 150 Ko) n'est chargé que sur écran large ; sur téléphone, la liste équivalente seule s'affiche : conforme.

### Lisibilité à 360 px

- En-tête du site (bandeau, marque, recherche) : 179 px, commun à toutes les pages.
- Accueil : le champ salaire commençait à 621 px, hors du premier écran (titre de 71 px et chapeau de 93 px avant le formulaire).
- Résultat : titre de 144 px, puis le profil retenu, puis le total à 613-667 px (coupé par le bas de l'écran) et la phrase « sur 100 € » à 796-911 px. Rien de ce que la personne cherche n'était lisible sans défiler.
- Aucun débordement horizontal sur les cinq écrans.

### Textes ambigus et sigles

- Champ de l'accueil « Ton salaire net par mois » : le calcul attend le net avant impôt, et la page de saisie le dit (« Net à payer avant impôt sur le revenu ») ; un net payé après prélèvement à la source donne un résultat faux sans message.
- Texte d'exemple « 2 100 » dans le champ vide : se lit comme une valeur déjà saisie.
- Phrase-clé du résultat « Sur 100 € : 57 € Sécurité sociale, 30 € État… » : sans verbe, elle ne dit pas que ces euros vont à ces destinataires.
- Sigles (CSG, CRDS, TEOM, PLF, PLFSS, DGFiP, CADES, Unédic) : la première occurrence de chaque écran est déjà reliée au glossaire avec sa forme développée (`composants/sigles.ts`) : conforme.
- La consigne suggérait « Sur 100 € que tu paies » : la charte (règle 3) n'admet que « ce que tu verses » ; c'est la forme retenue.

### États vides et erreurs

- Résultat ouvert sans calcul : retour au formulaire avec un message : conforme.
- Calcul lancé depuis l'accueil : l'écran de passage affichait le formulaire complet et l'état « Calcul en cours » tout en bas, sous le formulaire (2 569 px), hors de vue sur téléphone ; l'annonce vocale « Calcul en cours » était remplacée par celle du titre de page. En cas d'erreur, rien en haut de l'écran ne le signalait.
- Moteur indisponible : repli sur le fil principal, puis message avec un lien vers le budget : conforme.

### Accessibilité (RGAA, WCAG AA)

- Contrastes : vérifiés par `contrastes.test.ts` dans les deux thèmes : conforme.
- Focus visible (anneau de 3 px) sur les liens, les champs et les parts du billet : conforme. Focus placé sur le titre de chaque nouvel écran : conforme.
- Libellés : tous les champs en ont un ; aucun identifiant en double ; aucun saut de niveau de titre sur les quatre écrans contrôlés.
- Billet découpé : liste des parts et tableau à côté ; fil de l'euro décrit en texte ; Sankey nommé (`role="img"`, `aria-label`) avec la liste des sous-blocs à côté : conforme.
- Liens « Suivre 1 € » ajoutés sur chaque ligne : nom accessible propre à chaque ligne (texte caché), pour ne pas lire dix fois le même lien.
- Aucun moyen de revenir au résultat depuis les pages suivantes (budget de l'État, suivre un euro, fiche de paie) sans repasser par le formulaire ou par l'historique du navigateur.

### Règle « calculé par le site » (règle 13)

- Budget de l'État : chaque grand poste affichait « sur ce que tu verses à l'État : X € par an », obtenu en répartissant la part de l'État au prorata du budget. Aucune source ne dit quel poste finance l'impôt d'une personne (attribution par déduction), et les deux montants ne portent pas sur la même année (calcul des revenus 2025, budget exécuté 2024 ou voté 2025) : non publiable.

## Les 10 corrections, par ordre d'impact

Mesures « avant » sur `origin/main`, « après » sur la branche `agent/parcours-principal`, mêmes conditions.

| N° | Problème | Correction | Avant | Après |
|---|---|---|---|---|
| 1 | Résultat hors du premier écran sur téléphone | Total puis phrase « sur 100 € » placés juste sous le titre, fourchette ensuite ; titre resserré sur téléphone (`h1.titre-resultat`) | 360 px : total à 613-667 px, phrase à 796-911 px ; 1 280 px : phrase à 729-789 px | 360 px : total à 419-469 px, phrase à 477-592 px (dans les 640 px) ; 1 280 px : phrase à 532-620 px |
| 2 | Attribution par déduction sur le budget de l'État (règle 13) | Montants « sur ce que tu verses à l'État » par poste retirés ; la page dit que cette part n'est pas fléchée et que le site ne la répartit pas | 12 montants par poste, au prorata, années différentes | 0 ; phrase de motif à la place |
| 3 | Phrase-clé sans verbe | « Sur 100 € que tu verses, 57 € vont à la Sécurité sociale, 23 € à l’État, 9 € aux collectivités locales et 11 € sans destinataire publié. » (cas de Lyon) ; source du calcul dans le même encadré | « Sur 100 € : 57 € Sécurité sociale, … » | phrase complète, somme des parts testée égale à 100 |
| 4 | Moteur de calcul téléchargé après le clic | Préchargement du Web Worker dès le focus du champ salaire de l'accueil (import dynamique, rien de plus au premier écran) | Entrée au résultat affiché : 2,69 à 2,80 s (4G simulée, CPU x4) | 1,85 à 1,99 s |
| 5 | Champ salaire de l'accueil hors du premier écran | Titre, chapeau et formulaire du héros resserrés sur téléphone (mêmes formes) | champ à 621-673 px | champ à 480-532 px |
| 6 | Libellé ambigu du champ de l'accueil | « Ton salaire net avant impôt, par mois », aide reliée au champ (ligne de la fiche de paie), texte d'exemple « Par exemple 2 100 » | « Ton salaire net par mois », exemple « 2 100 » | libellé et aide identiques à la page de saisie |
| 7 | Pas de passage direct du résultat au détail d'un prélèvement | Chaque ligne du résultat mène à sa piste « Suivre un euro » (clé publiée dans `prelevements/affectation.json`) ; le bouton principal suit la ligne la plus élevée | 0 lien par ligne ; bouton vers le budget de l'État entier | 1 lien par ligne chiffrée (23 dans le cas de Lyon, cotisations de l'employeur comprises) ; 1 clic du résultat à la piste d'un prélèvement |
| 8 | Budget de l'État bloqué par deux fichiers secondaires | Affichage après l'arbre et la part empruntée ; encadrés « deux méthodes », « jusqu'où on suit l'argent » et traçabilité complétés ensuite | 24 Ko de données attendus, affichage en 940 ms | 1,4 Ko attendus (arbre en cache), affichage en 423 à 432 ms |
| 9 | Écran de passage muet sur téléphone | État du calcul en haut de l'écran (`role="status"`), remplacé par un renvoi au message en cas d'erreur | état sous le formulaire, à 2 569 px | état sous le titre, à 375-518 px |
| 10 | Pas de retour au résultat depuis les pages suivantes | « Revenir à mon résultat » et « Modifier mon salaire » en haut du budget de l'État, de « Suivre un euro » et de la fiche de paie, seulement si un calcul a été fait (rien n'est enregistré) ; « Modifier ma saisie » dans l'encadré du total | 0 lien de retour ; « Modifier ma saisie » au-dessus du total | 2 liens sur chaque page suivante ; cibles de 44 px de haut |

Poids ajouté : module `retour-resultat` 0,2 Ko ; accueil +0,2 Ko, résultat +0,4 Ko, feuille de style +0,2 Ko (compressés). Budgets `bundle.test.ts` et `performance.test.ts` respectés (HTML prérendu : 46,9 Mo pour 47,5 Mo).

## Tests

`web/tests/parcours.test.ts` : de l'accueil au Sankey, au clavier (chaque action est un champ, un bouton de formulaire ou un lien ; envoi par la touche Entrée ; focus sur le titre de chaque écran), écran de 360 px simulé (ordre de lecture du résultat, règles de la feuille de style, pas d'ECharts chargé), lien de chaque ligne vers une clé publiée, absence de répartition par déduction, affichage du budget de l'État avant les fichiers secondaires.

## Ce qui reste

- En-tête commun (bandeau, marque, recherche) : 179 px sur téléphone avant tout contenu ; un en-tête plus court dégagerait le bouton « Découper mon billet » (690 px) et le reste du résultat. Hors du périmètre du parcours : composant partagé.
- Glossaire des sigles (27 Ko) chargé à chaque premier affichage, en concurrence avec les polices : le charger après l'affichage complet relève de `composants/sigles.ts`, partagé.
- Écran de passage `/calcul` : le calcul pourrait partir de l'accueil sans afficher le formulaire, ce qui demande de sortir la lecture du profil de `saisie.ts`.
- Lighthouse et axe-core ne sont pas installés dans le dépôt : contrôles faits par script et par lecture du code ; une passe axe-core sur ces cinq écrans reste à faire.
