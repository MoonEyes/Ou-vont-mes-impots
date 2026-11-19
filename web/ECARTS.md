# Écarts du calcul personnel face à OpenFisca (20 cas types)

Référence : `tests/cas_types/cas_types.json` (API OpenFisca, `openfisca-france` 175.0.45, revenus 2025, générée le 15/11/2026).
Moteur du site : `modele-social` 11.1.0 + `publicodes` 1.10.4, dans le navigateur.
Test : `npm test` (`tests/cas_types.test.ts`), tolérance 1 % exigée sur les cinq agrégats du contrat. Le test écrit le détail dans `ecarts_cas_types.json` (non versionné).

Hypothèses des tests, celles d'OpenFisca : effectif 50 (seuil modele-social « entre 50 et 149 »), pas de versement mobilité, taux AT-MP 0,7 %. Hors tests, le site affiche une fourchette sur ces paramètres (voir `SCENARIOS_SITE` dans `src/calcul/moteur.ts`).

## Résultat : les 20 cas passent

| Agrégat | Écart maximal | Cas |
|---|---|---|
| Salaire brut | 0,006 % | C06 |
| Cotisations salariales | 0,05 % | C06 |
| CSG | 0,006 % | C06 |
| CRDS | 0,007 % | C18 (personne 2) |
| Impôt sur le revenu du foyer | 0,35 % (1 €) | C03 : 289 € contre 288 € |

Impôt : 18 cas identiques à l'euro ; C03 (+1 €) et C17 (1 651 € contre 1 650 €, +0,06 %) viennent des arrondis intermédiaires (décote et quotient familial arrondis différemment par les deux moteurs).

## Ajustements faits pour retrouver la législation 2025 (pas des retouches de résultat)

1. **Complémentaire santé et prévoyance d'entreprise exclues** (`prévoyances . santé . montant` et `prévoyances . employeur . cadres` à 0). modele-social met par défaut une mutuelle de 40 €/mois et la prévoyance cadre, absentes d'OpenFisca et variables d'un employeur à l'autre. Sans cet ajustement, la CSG des cadres s'écartait de 1,4 % (prévoyance patronale réintégrée dans l'assiette).
2. **Impôt sur le revenu au barème des revenus 2025** : modele-social date ses barèmes à l'année de paiement ; le site évalue l'impôt à la date du 1er janvier 2026 (tranche à 0 % jusqu'à 11 600 €, décote 897 € / 1 483 €), avec l'abattement de 10 % appliqué à chaque salaire séparément puis le quotient familial du foyer (parts des enfants calculées par le site pour la garde alternée).
3. **Cotisations patronales 2025** : modele-social 11 ne code que la loi 2026 (RGDU jusqu'à 3 SMIC, suppression des taux réduits). Pour les revenus 2025, le site applique la réduction générale 2025 (coefficient T = 0,3194 ou 0,3234, nulle à partir de 1,6 SMIC), le taux maladie de 7 % jusqu'à 2,25 SMIC et le taux allocations familiales de 3,45 % jusqu'à 3,3 SMIC (`reductionGenerale2025` et `situationSalarie`). Avant cet ajustement, les cotisations patronales nettes s'écartaient de +306 % au SMIC et de +26 % au salaire médian.

## Écarts restants, hors critère (cotisations patronales)

Les cotisations patronales ne font pas partie des agrégats exigés ; elles sont affichées dans un bloc séparé, en fourchette. Écarts constatés avec les hypothèses d'OpenFisca :

| Cas | Patronal avant réduction | Réduction générale | Patronal net |
|---|---|---|---|
| Non-cadres (C01 à C05, C08 à C11, C13 à C16, C17 et C19 personne 2) | +0,10 % | +0,02 % au SMIC, 0 % au-delà | +0,11 % (médian), +1,04 % à +1,15 % (SMIC) |
| C06, C17, C19 (cadre 3 800 €) | −3,02 % | 0 % | −3,02 % |
| C07 (cadre 6 500 €) | −1,69 % | 0 % | −1,69 % |
| C12 (cadre 4 500 €) | −2,56 % | 0 % | −2,56 % |
| C18 (cadres 5 000 € et 4 000 €) | −2,21 % et −2,87 % | 0 % | −2,21 % et −2,87 % |
| C20 (cadre 10 000 €) | −1,08 % | 0 % | −1,08 % |

Explications :

- **Cadres (−1 % à −3 %)** : OpenFisca compte dans `cotisations_employeur` la prévoyance obligatoire des cadres (1,5 % de la tranche 1, soit 706,50 € par an dès que le brut dépasse le plafond de la Sécurité sociale). Le site l'exclut volontairement (point 1 ci-dessus). Pour C06, 706,50 € expliquent 96 % de l'écart de 738 €.
- **SMIC (+1,04 %)** : l'écart absolu est le même que pour les autres non-cadres (environ 7,50 € par an sur 7 543 € avant réduction) ; rapporté à un patronal net de 553 € après réduction générale, il dépasse 1 %.
- **Non-cadres (+0,10 %)** : environ 7,50 € par an, non attribué à une ligne précise (arrondis de taux de contributions à la formation et au logement entre les deux moteurs).

## À surveiller

- Une nouvelle version de modele-social codant la législation 2025 rendrait les ajustements du point 3 inutiles : les retirer et relancer `npm test`.
- Si le contrat ajoute les cotisations patronales aux agrégats exigés, il faudra décider de réintégrer la prévoyance cadre (et donc la mutuelle) dans le calcul.

---

# Profils étendus (`calculerProfil`) : 44 cas types

Référence : `tests/cas_types/cas_types_profils.json`, générée le 17/11/2026 par `tests/cas_types/generer_reference_profils.py` à partir de l'API OpenFisca (`openfisca-france` 175.0.45) et de l'API mon-entreprise de l'Urssaf. Millésime : revenus 2025. Test : `tests/cas_types_profils.test.ts` (tolérance 1 % ; `ECARTS_PROFILS=1 npm test` écrit le détail dans `ecarts_cas_types_profils.json`, non versionné). API : `src/calcul/README.md`.

L'API mon-entreprise repose sur la même base de règles que le site (modele-social) : elle vérifie l'intégration (situation transmise, dates), pas la règle. OpenFisca est une source indépendante.

## Résultat : les 44 cas passent

| Profil | Cas | Référence | Agrégats exigés | Écart maximal |
|---|---|---|---|---|
| Fonctionnaire titulaire (État, territoriale, hospitalière) | F01 à F05 | OpenFisca | brut, retenue pension + RAFP, CSG, CRDS, imposable, impôt | 0,06 % (F04, impôt 1 740 € contre 1 741 €) ; cotisations identiques au centime |
| Contractuel de droit public | P01 à P03 | OpenFisca | brut, cotisations (vieillesse + Ircantec), CSG, CRDS, imposable, impôt | 0,13 % (P03, cotisations) |
| Retraité | R01 à R05 | OpenFisca | pension brute, CSG, CRDS, Casa, pension nette et imposable, impôt | CSG, CRDS, Casa identiques ; impôt 3 € (R03, 165 € contre 168 €) |
| Micro-entrepreneur | M01 à M06 | mon-entreprise (cotisations), OpenFisca (impôt, versement libératoire) | forfait et ses 5 postes, formation, taxe de chambre, versement libératoire, impôt | 0,002 % |
| Foyers à deux natures de revenus, parent isolé | X01 à X06 | OpenFisca, mon-entreprise | agrégats de chaque personne, impôt du foyer | 0,03 % (X02, impôt 2 981 € contre 2 982 €) |
| Alsace-Moselle | A01 à A03 | OpenFisca corrigé, mon-entreprise | brut, cotisations, cotisation du régime local, CSG, CRDS, impôt | 0,05 % (A03, cotisations) |
| Apprenti | E01 à E03 | mon-entreprise ; OpenFisca pour E01 | brut, cotisations, CSG, CRDS | 0,004 % |
| Temps partiel | T01 à T04 | OpenFisca | brut, cotisations, CSG, CRDS, impôt | 0,06 % (T03) ; T04 (impôt calculé 38 €, sous le seuil de 61 €) : 0 € contre 0 €, écart nul |
| SMIC et réduction générale | S01 à S03 | OpenFisca | les mêmes, plus la réduction générale | 0,02 % (S01, réduction générale) |
| Outre-mer (Guadeloupe, Martinique, Guyane, La Réunion) | D01 à D06 | OpenFisca (commune transmise : réduction d'impôt de l'article 197, I-3), mon-entreprise (micro) | agrégats du profil, impôt du foyer avec la réduction | 0,14 % (D04, impôt 717 € contre 718 €, abattements des retraités, point 2) ; cotisations 0,06 % (D06) ; impôt identique à l'euro pour D01, D02 (plafond de 4 050 € atteint), D03, D05, D06 |

## Corrections et tolérances documentées

1. **Alsace-Moselle** : OpenFisca 175.0.45 applique 1,5 % (taux en vigueur jusqu'au 31/03/2022) ; le droit en vigueur est 1,3 %. La référence retire 0,2 % de l'assiette aux cotisations salariales d'OpenFisca et l'ajoute au net et au salaire imposable ; l'impôt est recalculé par OpenFisca à partir du salaire imposable corrigé. L'API mon-entreprise, à 1,3 %, donne le même brut à 0,007 % près.
2. **Impôt des foyers avec un retraité** : OpenFisca garde pour 2025 les abattements des revenus 2024 (pensions : minimum 450 €, plafond 4 399 € ; plus de 65 ans : 2 795 € et 1 398 €). Le site applique ceux des revenus 2025 (454 € et 4 439 € ; 2 822 € et 1 411 €). Tolérance sur l'impôt de ces foyers : 1 % ou 5 €. Écart constaté : 3 € au plus.
3. **Cotisation maladie de 1 % sur la retraite complémentaire** : OpenFisca en publie le taux mais ne la calcule pas. Le taux a été relu dans ses paramètres ; le montant (1 % de la pension complémentaire brute) n'est pas recoupé par un calcul tiers. Les comparaisons de pension nette et d'impôt se font hors cette cotisation.
4. **Fonctionnaires** : OpenFisca ajoute d'office une indemnité de résidence, un supplément familial et l'indemnité compensatrice de CSG. Le profil du site les attend dans `primes_mensuelles` ; la référence les met à 0 dans OpenFisca.
5. **Apprentis** : OpenFisca ne modélise que l'exonération totale des contrats conclus avant mars 2025 sous 79 % du SMIC (cas E01). Pour E02 et E03, la seule référence est mon-entreprise ; leur impôt (nul, salaire sous l'exonération à hauteur du SMIC annuel) n'est pas recoupé.
6. **Versement libératoire** : l'impôt des autres revenus du foyer est calculé au taux effectif (impôt brut sur le revenu total, réduit au prorata, décote ensuite), ordre vérifié sur X03 et M04 à M06.
7. **Outre-mer** : OpenFisca n'a pas de seuils de CSG sur les pensions propres à l'outre-mer ; le profil d'un retraité d'outre-mer porte le taux du relevé et la référence transmet un revenu fiscal de référence de métropole de la même tranche (D04). Seuil de mise en recouvrement de 61 € (CGI art. 1657, 1 bis) : le site l'applique comme OpenFisca (`impot_revenu_restant_a_payer`) depuis le 19/11/2026 ; il affiche 0 € prélevé et une ligne « impôt calculé X €, non recouvré car inférieur à 61 € ». Cas type dans la zone du seuil : T04 (impôt avant seuil 38 € pour les deux moteurs, `ip_net` d'OpenFisca).

## Hors critère : part employeur

| Profil | Écart avec OpenFisca | Explication |
|---|---|---|
| Fonctionnaire de l'État | −1,04 % | Chaque ligne (pension 78,28 %, ATI, RAFP, maladie 9,70 %, allocations familiales, FNAL, CSA) est identique au centime ; le total d'OpenFisca contient en plus 1 % du traitement, non attribué à une ligne publiée. |
| Fonctionnaire territorial ou hospitalier | 0,00 % | Deux écarts qui se compensent : maladie à 9,88 % sur le site (taux 2025) contre 8,88 % dans OpenFisca (taux de 2024 seulement), et le même 1 % non attribué côté OpenFisca. |
| Contractuel de droit public | −0,9 % | Même 1 % non attribué côté OpenFisca ; le site compte en plus l'AT-MP (0,7 % dans les hypothèses de test), absente d'OpenFisca pour ce statut. |
| Salariés (Alsace-Moselle, temps partiel, SMIC) | +0,1 % à +1,15 % ; cadres −3 % | Mêmes causes que pour les 20 cas du contrat 1.0 (ci-dessus). |

## Désactivé par défaut (non vérifié)

- **Indépendant au régime réel** (artisan, commerçant, profession libérale) : modele-social le calcule avec l'assiette réformée en 2025, OpenFisca avec l'assiette antérieure (écart de l'ordre de 20 % sur un revenu de 20 000 €). Sans référence indépendante concordante, le profil renvoie `independant_reel_non_verifie`, sauf option `autoriserNonVerifie`.
- **Régime local d'Alsace-Moselle hors salarié du privé** : pensions de retraite (refusé dans tous les cas), contractuel de droit public, apprenti, taxe de chambre de métiers du micro-entrepreneur artisan.

## Prélèvements sans affectation dans `prelevements/affectation.json`

Lignes portant le destinataire « non publié » (aucune répartition supposée), avec la clé proposée :

| Lignes | Clé proposée |
|---|---|
| Retenue pour pension civile, contribution employeur au CAS Pensions | `pension_civile_etat` |
| Retenue et contribution CNRACL | `cnracl` |
| RAFP (agent et employeur) | `rafp` |
| ATI, ATIACL, fonds pour l'emploi hospitalier | `allocation_temporaire_invalidite`, `atiacl`, `fonds_emploi_hospitalier` |
| Ircantec (agent et employeur) | `ircantec` |
| CSG sur les pensions (déductible et non déductible) | `csg_remplacement` |
| Casa | `casa` |
| Cotisation maladie sur la retraite complémentaire | `maladie_retraite_complementaire` |
| Forfait micro-social : maladie-maternité, invalidité-décès, retraite de base, retraite complémentaire, formation | `independants_*` |
| Taxe pour frais de chambre consulaire | `taxe_frais_chambre_consulaire` |
| Cotisation maladie du régime local d'Alsace-Moselle | `regime_local_alsace_moselle` |

Déjà sans entrée avant cette extension (destinataire du contrat 3.5 conservé) : CET, Apec, AGS, formation professionnelle, taxe d'apprentissage, versement mobilité, forfait social, réduction générale.
