# Audit avant lancement public (18 et 19/11/2026)

Auditeur indépendant (aucune page du site écrite par lui). Périmètre : les 58 routes de `web/src/routes.ts`, les 2 410 pages prérendues (`npm run build`), les fichiers publiés de `site/data` (745 Mo, environ 12 000 fichiers JSON) et les règles `docs/NEUTRALITE.md`, `docs/lexique_neutre.json`, règles 1 à 13 des agents.

## Méthode

1. Neutralité : balayage du texte visible des 58 routes prérendues (plus Lyon, Nantes et les pages des départements 44 et 69), soit 42 827 lignes uniques, avec une liste élargie au-delà du lexique (heureusement, record, dérive, flambée, « grâce à », « à cause de », « donc », « seulement », comparatifs, « plus gros », « fort », « faible »...) ; lecture des chapeaux et titres des pages Vie politique, Collecte et contrôle (recouvrement et fraude), Comparaison européenne, Communes comparables (Croiser), Cibles et résultats, Une organisation ; relecture des couleurs (charte règle 7) et des règles d'ordre.
2. Confidentialité : un échantillon raisonné, puis des recherches systématiques sur toutes les chaînes de `site/data` : courriels, téléphones, civilités (M., Mme, Monsieur, Madame), « né le », adresses (numéro suivi d'un type de voie), prénom fréquent suivi d'un nom (liste de 250 prénoms, plus large que les 17 prénoms de repli de `pipeline/local.py`), puis contrôle de chaque famille de clés (dénominations, objets, projets, opérations, délibérations) avec `sirene.personne_morale`, `local.objet_publiable`, `associations.nom_de_personne_seul`.
3. Chiffres : recherche des calculs faits par les écrans (`/ pop`, sommes, parts) et de l'usage de `badgeCalcule` ; contrôle des absences (« non publié », jamais 0) par les tests existants.
4. Accessibilité et clarté : sigles de trois lettres ou plus affichés dans les pages prérendues sans entrée au glossaire ; repérage des phrases les plus longues et les plus chargées en sigles et en termes techniques.

## Corrections faites (commit de la branche `agent/audit-lancement`)

| Type | Nombre | Détail | Test |
|------|--------|--------|------|
| Confidentialité : adresses de biens privés | 125 objets retirés dans 57 fichiers `local/decisions/*/index.json` | `deliberations_subventions` publiait des objets comme « Attribution de subvention pour restauration du patrimoine immobilier privé - dossier 1 rue … », « Subvention urbanisme 12 rue … », « ravalement de façades 5 rue … » : ils désignent le bien d'un particulier. `pipeline/deliberations.py` les excluait déjà (motif `adresse_possible`) mais pas `pipeline/local.py`. Nouveau `local.objet_avec_adresse` (même motif `ADRESSE_NUMERO_RE`), appliqué dans `deliberations_subventions` et aux données publiées. | `tests/test_confidentialite.py` |
| Confidentialité : personne qui domicilie une association | 9 dénominations dans `associations/programmes/` (131, 163_1, 163_2, 175, 224) | « ASSOCIATION APAX CHEZ M. Prénom Nom », « … CHEZ MME Nom - 02 », etc. Nouveau `associations.sans_domiciliation` : la partie « chez M. … » est retirée, le montant reste nommé sous le SIREN (personne morale 9220). | idem |
| Confidentialité : nom de personne sans SIREN | 2 organisations du répertoire HATVP (`controle/lobbying/organisations.json`) | Dénominations « Prénom Nom » ou « Prénom Nom Consultants » avec un identifiant HATVP et sans SIREN : aucune catégorie juridique ne prouve une personne morale. Passées dans `exclus` (nouveau motif « dénomination qui ressemble à un nom de personne, sans SIREN ») ; `pipeline/controle.py` applique désormais `associations.nom_de_personne_seul` hors SIREN. | idem |
| Confidentialité : téléphone | 1 dénomination (`ue/beneficiaires/34.json`) | Numéro de téléphone collé à la dénomination d'une association bénéficiaire. Nouveau `ue.sans_telephone`. Nouveau test transversal : aucun courriel dans `site/data`, aucun téléphone dans une clé de nom. | idem |
| Chiffre calculé par le site (règle 13) | pages commune, département (2 251 + 101 pages prérendues) | « dépensés par habitant » portait le badge « Tracé » alors que le site divise le montant par la population : badge « Calculé par le site » et méthode (`METHODE_PAR_HABITANT` dans `web/src/ecrans/commune.ts`), aussi sous chaque bloc budgétaire qui affiche des euros par habitant. | `web/tests/calcule.test.ts` |
| Sigles sans définition | 16 entrées ajoutées à `web/src/glossaire.json` | APL, ALF, ALS, PAJE, DGAFP, DARES, DEPP, SDES, SRE, CNBF, FNAL, CEG, CNDS, CNC, DITP, CIRAD (définition courte, source https). | `web/tests/glossaire.test.ts` |
| Lexique neutre | 1 règle ajoutée à `docs/lexique_neutre.json` | (mal)heureusement, hélas, record, dérive, flambée, s'envoler, dramatique, alarmant, inquiétant. Aucune occurrence aujourd'hui : la règle empêche une régression. | `tests/test_neutralite.py`, `web/tests/ecrans.test.ts` |

Vérifications : `python3 -m pytest -q` complet (4 322 réussis, 36 ignorés), `python3 docs/valider_contrat.py --strict` (0 orphelin), `npm ci`, `npx vitest run` (688 réussis), `npm run build` (2 410 pages).

## Constats sans correction, par gravité

### Moyenne

1. Filtre de prénoms dépendant d'un cache absent du dépôt. Sans `data/lake/_cache/local/prenoms.json` ni stock SIRENE, `local.prenoms()` et `associations.prenoms()` retombent sur 17 prénoms (`PRENOMS_MINIMAUX`). Une reproduction sur une machine neuve publierait des objets et dénominations que la production filtre (le balayage avec 250 prénoms ne trouve rien aujourd'hui dans les textes libres : la production a donc bien tourné avec la liste complète). Recommandation : versionner la liste de prénoms dérivée (quelques Ko) avec sa source, et faire échouer le pipeline si elle manque.
2. Élus nommés hors des deux exceptions de la règle 5. Les auteurs d'amendements (`decisions/programme_*.json`, clés `auteur` et `nom`, environ 2 000 occurrences) et les députés qui déposent une motion de rejet (`decisions/scrutins.json`, « déposée par Mme … ») sont nommés. La charte (règle 6) l'assume pour les amendements ; la règle 5 des agents ne prévoit que les candidats (comptes de campagne) et la réserve parlementaire. À arbitrer par le propriétaire et à écrire dans une seule règle.
3. Titre officiel d'opération européenne avec un groupe ethnique et une adresse : « Accompagnement social de 34 familles Roms du site 165 rue de Paris à Bobigny » (`fonds_europeens/operations`). Aucune personne nommée, mais une adresse liée à un groupe identifiable ; `texte_publiable` n'est pas appliqué aux intitulés d'opérations Kohesio. Proposition : appliquer le filtre d'adresse aux intitulés d'opérations.
4. Agrégats HATVP non recalculés : `totaux_par_annee` et `lobbying/ministeres.json` comptent encore les 2 organisations passées dans `exclus` (aucun nom) ; ils se corrigeront à la prochaine production de `pipeline/controle.py`.

### Faible

5. Personnes citées comme auteurs de sources réutilisées : « relevé par M. … (mémoire Sciences Po, dépôt MIT) » (`niches/index.json`, titre et producteur de la source igf2011), un économiste auteur de pages d'analyse (`assurance_maladie_territoires/index.json`), des identifiants GitHub (`petite_enfance/index.json`). Attribution d'œuvres réutilisées, pas des bénéficiaires ; garder seulement si la licence l'exige, sinon citer le dépôt.
6. Organismes de formation nommés dont la dénomination Sirene ressemble à « NOM Prénom (sigle) » (`formation/elus.json`, `formation/cpf_organismes.json`) : catégorie juridique de personne morale vérifiée par le pipeline, mais une société d'exercice au nom de son dirigeant reste identifiante. Contrôle manuel conseillé.
7. Collecte et contrôle : la page reprend, entre guillemets et avec son auteur, l'interprétation du Haut Conseil du financement de la protection sociale (« effort de contrôle accru, pas une hausse de la fraude »). Citation sourcée, mais c'est la seule lecture proposée : ajouter « selon le Haut Conseil » en tête de phrase partout où elle apparaît.
8. Libellés « Les plus gros montants » (Marchés publics) : neutre mais familier ; « Les montants unitaires les plus élevés » est plus homogène avec le reste du site.
9. Numéros de délibération en forme de téléphone (`0110202404`, `02-2025-22-12-2025`) et adresses d'équipements publics dans les projets subventionnés : vérifiés, ce ne sont pas des données personnelles.

### Neutralité : résultat du balayage

Aucun terme du lexique ni de la liste élargie dans le texte visible des pages : pas de « gaspillage », « trop », « heureusement », « dérive », « explosion », « scandale », « record », « à peine » ; « seulement » n'apparaît que dans des phrases de méthode (« publié par programme seulement »), jamais avant un montant. « Donc » et « à cause de » relient des définitions de méthode (consolidation, périmètre), jamais deux chiffres de politique. Couleurs : aucune couleur de valeur ; la France est repérée par le mot et un contour sur la page européenne ; partis, candidats et amendements suivent un ordre écrit sous chaque liste. Chapeaux des pages Vie politique, Collecte et contrôle, Comparaison européenne, Communes comparables, Cibles et résultats, Une organisation : descriptifs, avec la limite écrite (« La page ne dit pas si l'argent a produit le résultat », « ne dit pas pourquoi une commune dépense plus ou moins »).

### Chiffres

Les écrans qui calculent (somme des fonds européens, organisation, croiser, projets, hôpitaux, fonction publique, solidarités des départements) appellent `badgeCalcule` avec une méthode. Le seul écart trouvé (euros par habitant des collectivités) est corrigé. Les absences sont rendues « non publié » ; les sources et millésimes sont présents sur chaque bloc (tests existants `regles.test.ts`, `calcule.test.ts`).

## Les 15 passages les plus difficiles pour le grand public

| N° | Page | Passage (début) | Difficulté |
|----|------|-----------------|------------|
| 1 | Suivre un euro | « Hors ONDAM et écart de champ avec l'ONDAM (non ventilé) … net de la part AT-MP comprise dans l'ONDAM (IJ et soins des accidents du travail) » | six sigles dans une phrase de 75 mots |
| 2 | Méthode | « Les points de chaque destinataire pour 2025 sont lus dans l'annexe 3 du projet de loi de financement de la sécurité sociale … 1,88 point pour … » | suite de points de CSG et de sigles ; un tableau serait plus lisible |
| 3 | Une organisation | « Lignes publiées sans SIREN … nom normalisé … comparé … par Splink (modèle …) » | vocabulaire d'appariement statistique |
| 4 | Solidarités des départements | « Méthode des comptes : agrégats de l'OFGL repris tels quels, lus par SIREN (le code 67A … ) » | jargon de base de données |
| 5 | Retraites | « Contribution au FSPOEIE et au RATOCEM … » | sigles non développés dans le libellé repris |
| 6 | Justice et défense | « Type de quartier : MA/QMA maison d'arrêt, CD/QCD …, CSL/QSL …, SAS … » | dix sigles pénitentiaires |
| 7 | Le numérique de l'État | « Un changement de nom déclaré dans le code (pipeline/numerique_etat.py, RENOMMAGES) est appliqué seulement si … » | nom de fichier et de constante du code |
| 8 | Méthode, fraîcheur | « le serveur cnsa.fr ne transmet pas son certificat intermédiaire : le téléchargement est refusé par la vérification TLS » | vocabulaire technique réseau |
| 9 | Méthode, fraîcheur | « collecte/collecte.py ne tient pas de session : le module lit les pages publiques … » | vocabulaire de développeur |
| 10 | Fonction publique | source citée par une adresse d'API Eurostat de 300 caractères (D1, TE, S13, S1311) | adresse brute au lieu d'un titre |
| 11 | Sécurité sociale | « PLACSS 2024, annexe 7 … (CRPA L. 321-1) » | sigles et référence juridique sans explication |
| 12 | L'État actionnaire | « Le SIREN retenu est celui de la société TSA (catégorie juridique 5710 …) » | codes administratifs |
| 13 | Collecte et contrôle | fiche « Manque à gagner de TVA dû à la sous-déclaration … » (producteur, publication, année, périmètre sur une ligne de 90 mots) | densité |
| 14 | Hôpitaux | notice de licence de la CNSA (« notspecified », loi n° 2016-1321) | discussion de licence dans le corps de page |
| 15 | Comparaison européenne | note Eurostat en anglais (COFOG, NATO methodology, ESA 2010) | langue (balisée `lang="en"`, sans résumé français) |

Recommandations : déplacer les détails de pipeline (noms de fichiers, constantes, TLS) dans la page Méthode ou dans le dépôt ; remplacer les adresses d'API par le titre du jeu ; résumer en français les notes Eurostat ; mettre les répartitions en points de CSG dans un tableau.
