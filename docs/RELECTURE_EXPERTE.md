# Relecture experte : pages et chiffres à faire vérifier en priorité

Complète l'étape 3 du plan de lancement (document « Lancement public : Où vont mes impôts ») : le plan donne les profils de relecteurs, ce fichier donne, page par page, les chiffres à contrôler, leur source et la méthode du site. Sources et millésimes relevés dans `site/data` au 19/11/2026 (commit `3dac12f9`).

Ordre de priorité : ce que verra chaque visiteur d'abord (calcul, accueil), puis les pages les plus partagées (commune, budget de l'État), puis les estimations.

## Consigne commune aux relecteurs

Pour chaque chiffre : (1) la source citée sur la page est-elle la bonne ? (2) l'année et le périmètre affichés sont-ils ceux de la source ? (3) le libellé est-il exact dans votre métier ? (4) un écart entre deux sources est-il présenté sans être tranché ? Les remarques se notent avec l'adresse de la page et le texte exact, ou par « Signaler une erreur » en bas de page. Ne pas juger l'opportunité d'une dépense : seulement l'exactitude.

## Priorité 1 : le calcul personnel

| Page | Chiffres à vérifier | Source | Méthode du site | Relecteur |
|---|---|---|---|---|
| `/calcul/` puis résultat | Cotisations salariales et patronales, CSG, CRDS, impôt sur le revenu pour 3 profils (1 400, 2 100, 4 000 € net par mois ; célibataire, couple avec 2 enfants). Exemple de recette : 2 100 € net par mois, 13 781 € versés par an | Barèmes Urssaf et DGFiP encodés dans `modele-social` (bibliothèque publique de l'Urssaf, moteur publicodes), version figée dans `web/package-lock.json` | Calcul exécuté sur l'appareil ; 20 cas types comparés à OpenFisca (`web/tests/cas_types.test.ts`) | Gestionnaire de paie, expert-comptable |
| `/calcul/bulletin` | Chaque ligne du bulletin, son taux, son plafond et l'organisme destinataire | Idem, plus nomenclature DSN | Libellés de `src/calcul`, contrôlés par `web/tests/bulletin.test.ts` | Gestionnaire de paie |
| Résultat, partie « à qui » | Part de chaque prélèvement attribuée à chaque destinataire (branches de la Sécurité sociale, État, collectivités, Unédic, retraites complémentaires) | PLFSS 2026 annexe 3 (tableau 31) ; PLF 2026 Voies et moyens tome I ; PLF 2026 compte « Pensions » ; circulaires Cnav 2024 et 2025 (`site/data/prelevements/affectation.json`, millésime 2025) | Part = fraction du produit 2025 du prélèvement attribuée à chaque destinataire ; une part introuvable est affichée « non publiée », jamais déduite | Fiscaliste, agent de la direction de la Sécurité sociale ou d'une Urssaf |
| Résultat, TVA et taxes hors bulletin | Estimation de la TVA et des accises payées sur la consommation | Insee (hypothèse de référence : taxes réparties comme la consommation ; variante imputée aux revenus), taux légaux | Estimation signalée comme telle, avec sa fourchette (central, bas, haut) ; voir `web/src/calcul/hors-bulletin.ts` | Économiste de la consommation, fiscaliste |

## Priorité 2 : les pages d'entrée les plus vues

| Page | Chiffres à vérifier | Source | Méthode du site | Relecteur |
|---|---|---|---|---|
| `/` (accueil) | Répartition « sur 100 € versés » (Sécurité sociale, État, collectivités, sans destinataire publié) | Même source que l'affectation ci-dessus | Exemple type (`web/src/exemple-lyon.json`) contrôlé par `web/tests/regles.test.ts` | Fiscaliste |
| `/explorer/etat/` | Sur 100 € dépensés par l'État, par mission ; bascule exécution 2024 et LFI 2025 | data.economie.gouv.fr (budget vert PLF 2026, crédits de paiement) ; PLRG 2025 annexe 1 | Crédits de paiement, au format PLF 2026 de la direction du budget ; exécuté, voté et proposé jamais mélangés | Agent d'une direction financière ministérielle, magistrat financier |
| `/explorer/secu/` | Dépenses et recettes par branche, exécution 2024 et 2025 | PLACSS 2024 et 2025, DSS, Unédic, DREES | Comptes publiés, sans retraitement | Agent de caisse de Sécurité sociale |
| `/local/<commune>/` (Nantes, Arras et deux communes de moins de 10 000 habitants) | Population, dépenses et dépenses par habitant, dette, DGF, taux votés | Comptes des communes 2022 à 2025 (DGFiP, data.gouv.fr), DGCL ; collecte du 16/11/2026 | Montants des comptes publiés ; par habitant = montant divisé par la population de la même année (badge « calculé par le site ») | Agent des finances d'une collectivité (hors CCEG) |
| `/explorer/dette/` | Encours, intérêts, détenteurs | Insee, Eurostat, BCE, programme 117 (data.economie.gouv.fr), Sénat, PLACSS | Encours 2025 en comptabilité nationale ; intérêts en comptabilité nationale et budgétaire présentés à part | Économiste des finances publiques |

## Priorité 3 : estimations et sujets sensibles

| Page | Chiffres à vérifier | Source | Méthode du site | Relecteur |
|---|---|---|---|---|
| `/explorer/niches/` | Coût des dépenses fiscales 2019 à 2026 (constaté jusqu'en 2024, estimé ensuite) | Voies et moyens tome II, PLF 2021 à 2026 (DGFiP) | Coûts tels que publiés ; « non chiffré » laissé tel quel, jamais 0 | Fiscaliste |
| `/explorer/recouvrement/` | Contrôle fiscal, contrôles Urssaf, estimations de fraude | DGFiP, Urssaf, HCFiPS, Cour des comptes, Commission européenne | Estimations de producteurs différents affichées côte à côte, jamais additionnées | Juriste ou fiscaliste |
| `/explorer/retraites/` | Prestations par régime 2004 à 2024, origine de l'argent | DREES (EACR), Service des retraites de l'État, PLF 2025, Caisse des dépôts, MSA | Comptes des régimes ; liens vers la Sécurité sociale et le budget de l'État | Agent d'une caisse de retraite |
| `/explorer/prestations/` | Montants versés par prestation, 2019 à 2025 | CNAF (data.caf.fr), DREES, Unédic, France Travail | Montants publiés par organisme payeur | Travailleur social, agent de CAF |
| `/beneficiaires/subventions/` | Totaux par source, bénéficiaires nommés | data.gouv.fr, data.ademe.fr ; SIRENE (stock du 1er novembre 2026) | Seules les sources marquées « additionne » sont sommées ; une personne physique n'est jamais nommée (catégorie juridique SIRENE) | Agent d'une collectivité qui verse des subventions |
| `/beneficiaires/marches/` | Montants notifiés 2019 à 2025 | DECP consolidées (data.gouv.fr, version du 18/11/2026) | Montant notifié hors taxes, maximum estimé pour un accord-cadre : ce n'est pas le montant payé | Acheteur public |
| `/explorer/comparaison-europe/` | Dépenses et prélèvements en part du PIB | Eurostat gov_10a_exp, gov_10a_taxag | Classification COFOG d'Eurostat, sans retraitement | Économiste |
| `/decisions/qui-a-vote/`, `/decisions/vie-politique/` | Rattachement d'un vote ou d'un amendement à un impôt ; présentation des élus et des candidats | Assemblée nationale et Sénat (données ouvertes, 17e législature) | Un texte est relié à un impôt seulement s'il cite un article de code qui fixe un paramètre du calcul | Deux relecteurs de sensibilités politiques différentes |

## Retour attendu

Un tableau par relecteur : page, texte exact, problème (source, année, périmètre, libellé, présentation), correction proposée avec sa source. Les corrections passent par le pipeline concerné, jamais par une modification à la main d'un fichier de `site/data`.
