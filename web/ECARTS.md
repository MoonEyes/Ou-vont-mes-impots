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
