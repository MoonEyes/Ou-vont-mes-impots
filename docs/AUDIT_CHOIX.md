# Ergonomie des éléments de choix : inventaire, mesures, corrections (19/11/2026)

Retour du propriétaire : « Il y a encore quelques soucis d'ergonomie et d'affichage sur les éléments où on fait des choix. »
Ce document recense tous les éléments de choix du site, les mesure avant et après, et décrit le jeu de composants partagé
qui les remplace (`web/src/composants/choix.ts`, styles `.choix-*` de `web/src/styles.css`, tests `web/tests/choix.test.ts`).

## Existant regardé (règle n°0)

| Source | Licence | Dernière publication | Verdict |
|---|---|---|---|
| Réglette `.bascule` et onglets de Ma commune (`brancherOnglets`), déjà dans le dépôt | MIT (dépôt) | 19/11/2026 | à adapter : onglets déplacés tels quels dans le composant partagé, réglette remplacée |
| Combobox de la recherche de l'en-tête (`composants/recherche.ts`, docs/AUDIT_RECHERCHE.md) | MIT (dépôt) | 19/11/2026 | réutilisée telle quelle (non touchée) |
| W3C APG, motifs Radio Group, Tabs, Switch | W3C Document License | en ligne | inspiration : rôles, flèches, Début, Fin, tabulation unique |
| `accessible-autocomplete` 3.0.2 (GOV.UK) | MIT | 24/09/2026 | inspiration seulement : même principe (la liste native reste la source) ; non repris : Preact embarqué, poids hors budget, style à refaire |
| `@zag-js/radio-group` 1.48.0 | MIT | 13/11/2026 | inspiration seulement : machines à états à brancher sur un framework ; le site écrit ses écrans en gabarits HTML |
| `govuk-frontend` 6.6.0 | MIT | 15/10/2026 | inspiration seulement : balisage des boutons radio et des cases |
| `@gouvfr/dsfr` 1.15.4 (Système de design de l'État, contrôle segmenté, interrupteur) | etalab-2.0 | 12/10/2026 | inspiration seulement : son usage est réservé aux sites de l'État, et le site, non officiel, ne doit pas en avoir l'apparence |

## Règle retenue : un composant par type de choix

| Choix | Composant | Rendu |
|---|---|---|
| 2 à 4 options courtes (26 caractères au plus), effet dans la page | `segmente()` | groupe radio ARIA de boutons ; un seul atteint par Tab ; flèches, Début, Fin ; la sélection suit le focus |
| 5 à 12 options, ou libellés longs, ou option d'un formulaire | `radioListe()` | boutons radio natifs dans un fieldset ; pastilles en grille si les libellés sont courts, lignes sinon |
| plus de 12 options | `listeRecherche()` | liste native précédée d'un champ qui la filtre (sans accents ni majuscules), compteur annoncé, Entrée choisit la première option gardée, Échap vide le champ |
| la règle appliquée seule | `choix()` | choisit l'un des trois ci-dessus selon le nombre d'options et la longueur des libellés |
| choix qui change d'adresse (année, vue, territoire, impôt) | `choixLiens()` | liens, page courante `aria-current="page"` ; pastilles jusqu'à 4, en grille au-delà, en colonne si libellés longs |
| panneaux d'une même page | `listeOnglets()` | onglets ARIA, flèches, Début, Fin ; panneaux masqués, rien de retiré |
| réglage oui/non à effet immédiat | `interrupteur()` | case native de rôle `switch` ; curseur à gauche ou à droite |
| option d'un formulaire envoyé | `caseACocher()` | case native dans son libellé |
| option d'une liste détaillée (barre, montant, statut) | `optionRiche()` | bouton à état pressé (Suivre un euro) |

L'état choisi se voit sans la couleur : coche dessinée (segments, liens, options détaillées), graisse 800, contour épais et
pastille native (liste radio), trait souligné de 3 px (onglet), position du curseur (interrupteur). Cibles de 44 px au
moins partout. Lecture et écriture d'une valeur, quel que soit le composant : `valeurChoix()`, `fixerChoix()`,
`remplirListe()` (listes remplies plus tard, communes d'un département). Les choix envoient les mêmes événements qu'un
bouton radio natif (`input` puis `change`, seulement si la valeur change). Aucun stockage : l'état vit dans la page, ou
dans l'adresse pour les liens.

## Inventaire : 104 éléments de choix revus

Simulateur et résultat (accueil, `/calcul`, résultat, fiche de paie, et si, reçu, Suivre un euro) :

| Élément | Avant | Après |
|---|---|---|
| Accueil, Ton département (97) ; Ta commune (selon le département) | liste native | liste avec recherche (champ seulement au-delà de 12 communes) |
| Ton foyer (4 situations, libellés longs) | boutons radio sans composant | liste radio |
| J'habite en outre-mer | case | case partagée |
| Territoire d'outre-mer (6) | liste native avec « Choisir » | liste radio, erreur sur le groupe |
| Ta situation et Sa situation (9 chacune) | liste native groupée | liste radio |
| Versant, contrat d'apprentissage, montants de pension, taux de CSG, âge, nature de l'activité, versement libératoire (7 groupes par personne, 14 en tout) | boutons radio sans composant | liste radio partagée |
| Activité artisanale ; Préciser ma situation : statut cadre, frontalier, temps partiel (4 par personne, 8 en tout) | cases | cases partagées |
| Logement, voiture, tabac (3 chacun) | boutons radio | liste radio en grille de pastilles |
| Lieu de résidence (3, libellés longs) | liste native | liste radio, erreur sur le groupe |
| Département (102) ; Commune (selon le département) | listes natives | listes avec recherche |
| Ce que tu verses : contenu de la répartition (2) | réglette `aria-pressed` | segmenté |
| Fiche de paie : période (2), personne (2) | réglettes `aria-pressed` | segmentés |
| Et si : le salaire qui change (2) | boutons radio sans composant | segmenté |
| Reçu : afficher mes montants | case | interrupteur |
| Carte de partage : ajouter mes montants | case | case partagée |
| Suivre un euro : départs fréquents (6 ou 7), tous les prélèvements (35), montant suivi (2), pistes de chaque étape | réglettes `aria-pressed`, liste native | liste radio en grille, liste avec recherche, segmenté, options détaillées |

Ma commune et local :

| Élément | Avant | Après |
|---|---|---|
| Champ « Code postal ou nom » (Ma commune, Budget local), propositions et choix d'une commune quand un code postal en couvre plusieurs | liens sans flèches | flèche bas vers les propositions, flèches entre elles, Échap revient au champ |
| Onglets des quatre collectivités | onglets propres à l'écran, débordaient à 360 px | onglets partagés, deux rangées à 360 px |
| Budget local : département (102), commune | listes natives, première commune choisie d'office | listes avec recherche, « Choisir » par défaut |
| Comparer : département et commune, deux côtés | listes natives | listes avec recherche |
| Projets : département, dispositif, année | listes natives | listes avec recherche (champ selon le nombre) |

Explorer, bénéficiaires, décisions, méthode :

| Élément | Avant | Après |
|---|---|---|
| État : millésime (3) ; détail et Sécurité sociale : vue du budget (3 et 4) | réglettes de liens, état par la couleur | liens de choix (colonne si libellés longs) |
| Aide au développement : année (7), pays ou regroupement (163) | réglette, liste native | liens en grille, liste avec recherche |
| Comparaison européenne : poste (21), unité (2), année (25), ordre (2) | quatre listes natives | recherche, liens, recherche, liens |
| Éducation : région des lycées (3) | réglette `aria-pressed` | segmenté |
| Fonction publique : département ou région (118) | liste native | liste avec recherche |
| Fonds européens : région (22), liste d'opérations (6) | listes natives | liste avec recherche, liste radio |
| Formation professionnelle : année (7) | liste native qui changeait d'adresse | liens en grille |
| Hôpitaux : regrouper (3), année (5), département (104), type (3, libellés longs) | réglette, listes natives | segmenté, liste radio en grille, recherche, liste radio |
| Numérique de l'État : ministère (36), projets (2, libellés longs) | listes natives | recherche, liste radio |
| Opérateurs : mission (26), catégorie (11), trier par (4) | listes natives | recherche, liste radio, liste radio |
| Outre-mer : territoire (7) | réglette de liens | liens en grille |
| Prestations : département (102), année (7) | listes natives | recherche, liste radio en grille |
| Recettes : impôt (9) | liste native qui changeait d'adresse | liens en colonne |
| Retraites : régime (30) ; Séries : unité (3) ; Solidarités, Union européenne : département | listes natives, réglette | recherche, segmenté, recherche |
| Bénéficiaires : catégorie (3), programme (133) ; Marchés : année (7) ; Subventions : année (13) | réglettes, listes natives | liens, recherche, liens en grille, recherche |
| Application des lois : type de loi (9), année (25) | listes natives | liste radio, recherche |
| Contrôle, Résultats : département ; Vie politique : année (14) ; Votes : programme (134) | listes natives | listes avec recherche |
| Qui a voté : impôt (9), département (108), puis circonscription | liste native qui changeait d'adresse, liste native, liste désactivée | liens en colonne, recherche, consigne puis composant choisi par le nombre (une seule : choisie d'office) |
| Fraîcheur : statut (5), page du site (62), trier par (4, libellés longs) | listes natives | liste radio, recherche, liste radio |

Non repris : la recherche de l'en-tête (combobox ARIA déjà auditée, docs/AUDIT_RECHERCHE.md) et les champs de texte libre.

## Mesures avant et après

Chrome sans interface, 58 adresses (61 routes moins les pages de texte seul, plus Ma commune et Qui a voté avec
paramètres), 360 et 1 280 px, clair et sombre, focus clavier simulé, flèche droite sur le premier groupe de chaque page.
Script de recette hors dépôt (`outils-recette/mesure-choix.mjs`), mêmes adresses et même script pour les deux mesures.
Les écrans de résultat sont mesurés dans leur état d'exemple (sans calcul saisi).

| Mesure | Avant | Après |
|---|---|---|
| Contrôles de choix mesurés à 1 280 px | 143 | 249 (listes natives éclatées en options visibles) |
| Cibles sous 44 px (360 et 1 280 px, clair et sombre) | 0 | 0 |
| Groupes dont l'état choisi n'est porté que par la couleur | 14 sur 14 | 0 sur 19 |
| Focus clavier invisible | 7 sur 127 éléments | 0 sur 226 |
| Groupes où les flèches changent le choix | 1 sur 6 | 15 sur 15 |
| Éléments qui débordent de l'écran à 360 px | 3 (onglets de Ma commune) | 0 |
| Pastilles dont le texte passe mal à la ligne à 360 px | 2 | 0 |
| Listes natives de 2 à 4 options | 9 | 0 |
| Listes natives de 5 à 12 options | 13 | 0 |
| Listes de plus de 12 options avec recherche | 0 sur 30 | 30 sur 30 |
| Groupes de plus de 4 choix en réglette d'une ligne | 4 | 0 (grille ou colonne) |

Contraste de l'état choisi (après) : texte 16,7:1 en clair, 10,9:1 en sombre (segments, liens, onglets) ; option radio
choisie 16,7:1 et contour 14,9:1 en clair, 13,9:1 et 16,3:1 en sombre. Interrupteur du reçu vérifié au clavier (Espace),
cible de 44 px.

Poids (`npm run build`) : feuille de style 13,71 puis 14,36 Ko compressés ; module principal 28,23 puis 28,37 Ko ;
accueil 4,18 puis 4,24 Ko ; nouveau module `choix` 3,12 Ko, partagé par les écrans. HTML prérendu 40,6 Mo avant et après,
13 156 puis 13 157 fichiers. Budgets de `web/tests/performance.test.ts` et `web/tests/bundle.test.ts` respectés.

## Défauts corrigés, par catégorie

- État choisi porté par la seule couleur : 14 groupes (réglettes de l'État, des vues, des années, des territoires, de la
  fiche de paie, de Suivre un euro, des séries, des hôpitaux, de l'éducation, onglets) ; coche dessinée, graisse, trait.
- Clavier : 5 groupes de boutons sans flèches et 3 groupes radio hors composant ; tous les segmentés et onglets ont
  flèches, Début et Fin, un seul arrêt de tabulation ; champ de communes parcouru aux flèches.
- Composant inadapté au nombre d'options : 22 listes natives de 2 à 12 options, 30 listes longues sans recherche, 4
  réglettes de plus de 4 choix, 3 listes qui changeaient d'adresse à chaque flèche (formation, recettes, qui a voté).
- Affichage à 360 px : 3 onglets hors de l'écran, 2 pastilles coupées sur deux lignes ; les libellés longs passent en
  colonne.
- Focus : 7 éléments sans contour visible.
- Valeur par défaut : la première commune choisie d'office dans Budget local (désormais « Choisir ») ; liste des
  circonscriptions désactivée et vide (désormais une consigne, puis le choix).
- Erreur : un groupe radio en erreur est marqué `aria-invalid` et le focus va au bouton coché.
- Retour après le choix : compteur annoncé de la recherche (« 4 propositions sur 13. », « Aucune proposition ne contient
  ce texte. ») ; annonce inchangée des écrans qui en avaient une.
- Libellés (relecture UX) : « Rechercher dans la liste : … », « Choisis d'abord un département : ses circonscriptions
  s'affichent ici. », « Circonscription (10 dans ce département) », année « (en cours) ».
- Cohérence : un seul jeu de composants ; `tests/choix.test.ts` échoue si un écran écrit à la main une liste native, un
  bouton radio, une case, un état `aria-pressed` ou `aria-checked`, un rôle d'onglet ou la réglette `.bascule`.

## Ce qui reste

- Revue avec lecteur d'écran réel (NVDA, VoiceOver) : non faite, mesures automatiques seulement.
- La fenêtre d'une liste native (ouverte par le navigateur) ne se met pas en forme ; elle reste celle du système.
- Les options détaillées de Suivre un euro gardent un état pressé (`aria-pressed`) : il n'y a pas de motif ARIA de
  liste riche à choix unique mieux reconnu.
- Les choix par liens se parcourent à la touche Tab (ce sont des liens), pas aux flèches.
