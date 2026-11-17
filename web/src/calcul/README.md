# Calcul personnel : API du moteur

Tout le calcul se fait dans le navigateur, sans appel réseau. Millésime unique : **revenus 2025** (barèmes sociaux au 1er janvier 2025, impôt au barème appliqué en 2026). Moteur : `modele-social` 11.1.0 et `publicodes` 1.10.4, complétés par `baremes-2025.ts` pour ce que modele-social ne couvre pas (fonction publique, pensions).

Deux entrées :

| Fonction | Fichier | Usage |
|---|---|---|
| `calculer(profil, options)` | `moteur.ts` | Contrat 1.0 : salariés du privé, métropole hors Alsace-Moselle. Inchangé. |
| `calculerProfil(profil, options)` | `moteur-etendu.ts` | Tous les profils ci-dessous. Sur-ensemble : un profil du contrat 1.0 y est accepté. |
| `calculerProfilHorsFil(profil, options)` | `hors-fil.ts` | Même calcul dans le Web Worker (à utiliser depuis un écran). |
| `verifierProfilEtendu(profil, options)` | `moteur-etendu.ts` | Contrôle de saisie et de périmètre seul (`null` si calculable). |

## Entrée : `ProfilEtendu` (`types.ts`)

Champs communs du contrat 1.0 (`annee_revenus` = 2025, `residence`, `foyer`, `logement`, `personnes[]` avec `role` et `statut_activite`). Champs par profil, tous dans `personnes[i]` :

| Profil | `statut_activite` | Champs à saisir |
|---|---|---|
| Salarié du privé | `salarie_prive` | `salaire_net_avant_impot_mensuel`, `cadre`, `temps_travail` (`{type:'temps_partiel', quotite}` pour un temps partiel) |
| Apprenti | `apprenti` | `salaire_net_avant_impot_mensuel`, `apprentissage.contrat_avant_mars_2025` (booléen : le seuil d'exonération passe de 79 % à 50 % du SMIC et la CSG devient due pour les contrats conclus depuis le 1er mars 2025) |
| Fonctionnaire titulaire | `fonctionnaire` | `versant` (`etat`, `territoriale`, `hospitaliere`), `primes_mensuelles` (total brut des primes et indemnités, 0 possible), et soit `traitement_indiciaire_brut_mensuel`, soit `salaire_net_avant_impot_mensuel` (le traitement est alors retrouvé) |
| Contractuel de droit public | `contractuel_public` | `salaire_net_avant_impot_mensuel`, `temps_travail` |
| Retraité | `retraite` | `pension_base_mensuelle`, `pension_complementaire_mensuelle` (0 possible), `pension_saisie` (`nette_avant_impot` par défaut, ou `brute`), `csg_pension` : `{taux}` (`exonere`, `reduit`, `median`, `normal`, lu sur le relevé de pension) ou `{revenu_fiscal_reference, parts}` (avis d'impôt reçu en 2024, revenus 2023). `annee_naissance` sert à l'abattement d'impôt des plus de 65 ans. |
| Micro-entrepreneur | `independant` | `independant: {regime:'micro', activite, artisan, chiffre_affaires_annuel, versement_liberatoire}` ; `activite` = `vente`, `service_bic` (prestation commerciale ou artisanale), `service_bnc` (libérale, régime général) |
| Indépendant au réel | `independant` | `independant: {regime:'reel', categorie, revenu_professionnel_annuel}` ; **non vérifié, refusé sans `autoriserNonVerifie`** |
| Sans activité (conjoint) | `sans_activite` | rien |

Foyer : `foyer.situation` (`celibataire`, `parent_isole`, `couple_marie_pacse`, `couple_union_libre`) et `foyer.enfants[]`. Un couple peut mêler deux profils différents. Alsace-Moselle : `residence.alsace_moselle = true`.

`options` : celles de `calculer` (`scenarios`, `affectation` = contenu de `prelevements/affectation.json`, `commune`), plus `autoriserNonVerifie` (faux par défaut).

## Sortie : `ResultatEtendu`

Même forme que le résultat du contrat 1.0 (`prelevements[]`, `totaux`, `avertissements[]`), avec en plus :

- `entree.personnes[]` : `profil`, revenu net et brut de l'année, `revenu_imposable_annuel`, `detail` (traitement et primes, taux de CSG appliqué, pensions brutes) ;
- `millesime` : année et barèmes appliqués ;
- `verifications[]` : pour chaque profil du foyer, `statut` (`verifie` ou `non verifie`) et la référence utilisée ;
- `affectations_manquantes[]` : lignes sans entrée dans `prelevements/affectation.json`. Ces lignes portent le destinataire `non_affecte` (« Destinataire non publié dans les données du site ») et `statut_affectation: 'non sourcee'` ; aucune répartition n'est supposée. `cle_proposee` nomme l'entrée à créer côté données.

Familles de lignes : les cotisations personnelles d'un indépendant ou d'un retraité utilisent la famille `cotisation_salariale` (cotisations versées par la personne) ; le versement libératoire est une ligne `impot_revenu`.

Erreurs : `SAISIE_INVALIDE` (avec `champ`), `PROFIL_HORS_V1` avec `motif` : `dom`, `etranger`, `frontalier`, `demandeur_emploi`, `etudiant`, `sans_activite_seul`, `annee_non_couverte`, `independant_reel_non_verifie`, `retraite_alsace_moselle`, `independant_alsace_moselle_non_verifie` (régime local hors salarié du privé : contractuel, apprenti, micro-entrepreneur artisan).

## Ce qui est calculé, par profil

| Profil | Versé par la personne | Part employeur (hors total versé) | Source des règles |
|---|---|---|---|
| Fonctionnaire | retenue pour pension 11,10 % du traitement, RAFP 5 % des primes (plafonnées à 20 % du traitement), CSG, CRDS | CAS Pensions 78,28 % (État) ou CNRACL 34,65 %, ATI ou ATIACL, RAFP, maladie, allocations familiales, CSA, FNAL, versement mobilité, FEH (hospitalière) | `baremes-2025.ts` |
| Contractuel public | vieillesse de base, Ircantec (tranches A et B), CSG, CRDS | maladie 13 %, vieillesse, allocations familiales, AT-MP, CSA, FNAL, versement mobilité, Ircantec | modele-social + Ircantec dans `baremes-2025.ts` |
| Retraité | CSG au taux du revenu fiscal de référence, CRDS, Casa, cotisation maladie de 1 % sur la complémentaire | aucune | `baremes-2025.ts` |
| Micro-entrepreneur | forfait micro-social réparti (maladie, invalidité-décès, retraite de base et complémentaire, CSG, CRDS), formation, taxe de chambre consulaire, versement libératoire | aucune | modele-social |
| Apprenti, temps partiel, SMIC, Alsace-Moselle | lignes du salarié du privé ; en Alsace-Moselle, cotisation maladie du régime local 1,3 % | lignes du salarié, réduction générale 2025 | modele-social |
| Impôt du foyer | barème et quotient familial ; abattement de 10 % par salaire, de 10 % plafonné par foyer sur les pensions, forfaitaire sur le chiffre d'affaires micro ; abattement des plus de 65 ans ; taux effectif avec versement libératoire ; salaire d'apprenti exonéré jusqu'au SMIC annuel | | modele-social + `baremes-2025.ts` |

## Limites

- Une seule année : revenus 2025. Toute autre année renvoie `annee_non_couverte`.
- Fonctionnaires : contributions CNFPT, centre de gestion, ANFH non comptées ; militaires et magistrats non distingués ; indemnités de résidence, supplément familial et indemnité compensatrice de CSG à inclure dans `primes_mensuelles`.
- Contractuels : contribution chômage de l'employeur public non comptée (auto-assurance ou adhésion, selon l'employeur).
- Retraités : pas de lissage du taux de CSG en cas de franchissement de seuil une seule année ; seuils de métropole ; pas de régime local d'Alsace-Moselle ; la cotisation de 1 % s'applique à toute la pension saisie comme complémentaire.
- Micro-entrepreneurs : pas d'Acre, pas d'activité mixte, pas de professions libérales relevant de la Cipav ; l'éligibilité au versement libératoire (plafond de revenu fiscal de référence) n'est pas contrôlée.
- Impôt : sans autres revenus, frais réels, réductions ni crédits d'impôt.
- Vérification et écarts constatés : `web/ECARTS.md` ; cas types : `tests/cas_types/cas_types_profils.json`, test `web/tests/cas_types_profils.test.ts`.
