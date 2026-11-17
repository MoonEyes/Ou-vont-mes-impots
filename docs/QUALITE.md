# Qualité des données publiées : cohérence croisée

Relecture indépendante de `site/data/` (état du 17/11/2026) et de `docs/contrat_interface.md` (version 1.6). La relecture n'a modifié ni pipeline ni fichier de données ; les corrections ont été faites ensuite par les producteurs, le même jour : leur statut est en section 0, les constats d'origine sont gardés tels quels en section 1.

Test : `pytest tests/test_coherence.py` (sans réseau, sans `data/lake`). Chaque règle vérifiable est un test `test_Rnn_...`. Un écart publié et documenté est une **tolérance explicite** (constante `TOL_*`). Un vrai défaut se marque `xfail(strict=True)` avec la référence du constat : quand le producteur le corrige, le test passe, le xfail échoue et oblige à retirer la marque.

Bilan à la relecture : 53 règles (56 cas avec les paramètres), 48 vertes, 8 défauts en xfail ; 1 constat bloquant, 3 importants, 13 mineurs.

Bilan après correction : 54 règles (57 cas), toutes vertes, aucun xfail ni liste d'exceptions. 16 constats corrigés à la source (B1, I1 à I3, M1 à M11, M13), 1 documenté sans changement (M12), 1 nouveau constat mineur ouvert (M14).

## 0. Statut des constats après correction

| Id | Statut | Ce qui a été fait | Garde-fou |
|---|---|---|---|
| B1 | corrigé | Cause exacte : l'annexe 1 du PLRG 2023 publie trois cellules du programme 200 en notation scientifique de tableur (« 1,27055E+11 », « 1,39544E+11 », « 1,37322E+11 » : LFI, crédits ouverts, dépenses de la ligne « autres titres ») ; `montant()` de `pipeline/decisions.py` n'acceptait que des chiffres et renvoyait 0,0 pour tout le reste ; il ne restait que la ligne « titre 2 » (279,28 €). Un seul programme et une seule année touchés : 3 cellules sur les trois annexes 2023 à 2025, 1 170 valeurs de 135 programmes comparées à `realisations/`. `montant()` lit la notation scientifique et renvoie `None` pour une valeur non vide illisible (jamais 0) ; `lire_plrg()` publie alors `null` avec `valeurs_illisibles_plrg`, et signale l'arrondi de la source dans `precision_plrg` ; les amendements s'arrêtent sur une valeur illisible (`montant_strict`). Nouvelle étape `python pipeline/decisions.py plrg` : régénération ciblée des seuls champs du PLRG, sans archive JORF ; seul `decisions/programme_200.json` a changé. | contrôle bloquant en fin de `produire` et de `plrg` (`controler_realisations`) ; R25a (tous les programmes, sans exception), R25b, R25d ; `tests/test_unitaires_decisions.py` |
| I1 | corrigé | `transform.py` publie `ecart_consolidation_md` = `somme_administrations_md` - `total_consolide_md` (60,9) et, à part, `ecart_depenses_totales_md` (106,3) avec `definitions` ; l'écran Méthode lit les deux dans `meta.json`. | R28a ; `tests/test_pipeline.py` ; test web « méthode : l'écart de consolidation affiché… » |
| I2 | corrigé | `niches.py` : un coût `hors_reference` n'entre plus dans aucune somme par programme, mission ou grand poste ; il est publié dans `hors_reference_meur` (programme 343 : 19 M€ en 2024, `fiscal_meur` 0). Somme des programmes 2024 = 89 406 M€. | contrôle bloquant de `produire` ; R20f ; `tests/test_niches.py`, `tests/test_unitaires_niches.py` |
| I3 | corrigé | `fiscal_meur.<année>` = `null` et `mention.<année>` pour les 12 couples programme-année sans mesure chiffrée (151, 158, 345 : 2024 à 2026 ; 142 : 2024 ; 305, 101 : 2026) ; missions et grands postes comptent ces programmes dans `programmes_non_chiffres`. | R20g (équivalence dans les deux sens) ; schéma `niches_programmes` |
| M1 | corrigé | `dette.py`, `dette/interets.json` et contrat 2.19 : « Nantes, variante de comparaison ; le cas type C04 habite Lyon, 69123 ». | R14b |
| M2 | corrigé | fixtures web `dette/` recopiées des fichiers publiés. | R15b (égalité complète des quatre fichiers) |
| M3 | corrigé | `secu/index.json`, `liens_affectation.sans_noeud` : `acoss`, `msa_maladie`, `msa_vieillesse`, `msa_rco` avec motif et nœud englobant. Aucun montant n'est rattaché à un nœud par hypothèse. | R22b |
| M4 | corrigé | docstring de `scsp_par_programme` et contrat 2.14 : le plafond est la part de catégorie 32 × montant de l'arbre. | R16b |
| M5 | corrigé | note des 101 fichiers communaux réécrite (`dgf_commune_nouvelle` hors `dgf_totale`, DACOM comprise) ; EPCI : `dgf_ecart_composantes` publié pour les 199 lignes (47 EPCI) dont le total diffère de ses deux composantes. | R24a (EPCI : égalité exacte), R24b (1 267 lignes) |
| M6 | corrigé | note de `tva` dans `prelevements/affectation.json` : 208,82 Md€ (Eurostat) contre 210,0 Md€. | R21b (tolérance conservée) |
| M7 | corrigé | renvoi croisé (`renvoi`) entre `niches/sociales.json` et `controle/aides_entreprises.json`. | R30 (tolérance conservée) |
| M8 | corrigé | `dette/detenteurs.json`, `ecarts[]` : écart 2025 de 0,4 Md€ entre détenteurs et encours. | R29 |
| M9 | corrigé | `ue/contribution.json` et `ue/retours.json` se renvoient l'un à l'autre (24,3 arrondi, 24,356 déduit). | R08 (tolérance conservée) |
| M10 | corrigé | exception de `vie_politique/annees.json` écrite dans la règle `eur_sur_100` du contrat. | R31 |
| M11 | corrigé | `budget_arbre_meur` ajouté aux missions et grands postes (Engagements financiers de l'État : 58 764,6 M€) ; `budget_meur` gardé et défini. | R20d |
| M12 | documenté, inchangé | l'écran et `deficit.json` publient déjà le périmètre ; aucune donnée à corriger. | R27 (tolérance 3 %) |
| M13 | corrigé | `arbre_administrations/methode.json` : `depenses_totales_ensemble_md` et `ecart_tables_eurostat_md` (0,9). | `tests/test_pipeline.py` ; R28b |
| M14 | ouvert (nouveau, mineur) | `realisations/200.json`, exercice 2023 : LFI, crédits ouverts et dépenses viennent des mêmes trois cellules en notation scientifique, arrondies par la source à 6 chiffres significatifs (500 000 € près), sans mention ; « 137 322 000 279,28 € » affiche une précision que la source n'a pas. Correction proposée à `realisations.py` : mention de précision, comme `precision_plrg`. | aucun (à ajouter avec la correction) |

Régénérations : ciblées (`decisions.py plrg`, `niches.py produire` et `transform.py` rejoués sur les mêmes sources, notes et renvois réécrits dans les fichiers publiés à partir des constantes des pipelines). Fichiers de `site/data/` modifiés : `decisions/programme_200.json`, `niches/programmes.json`, `niches/sociales.json`, `arbre_administrations/methode.json`, `meta.json` (bloc `controle.arbre_administrations`, `genere_le` inchangé), `dette/interets.json`, `dette/detenteurs.json`, `secu/index.json`, `prelevements/affectation.json`, `ue/contribution.json`, `ue/retours.json`, `controle/aides_entreprises.json`, `local/dotations/epci.json` et les 101 `local/dotations/communes/*.json` (note seule).

## 1. Constats

### Bloquant

**B1. `decisions/programme_200.json`, exercice 2023 : montants du PLRG perdus.**
- Preuve : `annees.2023.depenses_cp` = 279,28 € et `lfi_cp` = 0, `ouverts_cp` = 0 ; le même PLRG 2023 lu par `realisations/200.json` donne `depense_constatee_eur` = 137 322 000 279,28 €, `vote_lfi_eur` = 127 055 000 000 €, `ouvert_en_gestion.total_eur` = 139 544 000 000 €. La `chronologie` publie « LFI votée : 0 € » et « Exécution : 279,28 € », affichées par l'écran Votes (`web/src/ecrans/votes.ts`, mouvements des 12 dernières étapes).
- Cause probable : `pipeline/decisions.py`, `montant()` renvoie `0.0` pour toute valeur qu'il ne sait pas lire (séparateur de milliers non reconnu, par exemple), puis `lire_plrg()` additionne : une absence devient 0 sans signal, contraire à la règle « `null` = donnée absente, jamais 0 ».
- Correction : `montant()` renvoie `None` (ou lève) sur une chaîne non vide illisible ; normaliser les espaces insécables (`\xa0`, ` `) comme `realisations.py` ; contrôle bloquant en fin de `produire` : `depenses_cp`, `lfi_cp`, `ouverts_cp` égaux à `realisations/<n>.json` à 1 € près pour chaque programme et année (règle R25a).
- Test : `test_R25b_decisions_programme_200_2023` (xfail B1) ; `test_R25a` vérifie tous les autres programmes et années (aucun autre écart).

### Importants

**I1. Écart de consolidation des administrations faux à l'écran Méthode.**
- Preuve : `arbre_administrations/methode.json` et `meta.json` (`controle.arbre_administrations`) : `somme_administrations_md` 1 732,7, `total_consolide_md` 1 671,8, `ecart_consolidation_md` 106,3. `web/src/ecrans/methode.ts` (l. 119) affiche « la somme des administrations (1 732,7 Md€) dépasse le total consolidé (1 671,8 Md€) de 106,3 Md€ » : la soustraction donne 60,9.
- Cause : `pipeline/transform.py` calcule `ecart_comptable` sur les dépenses totales TE de `gov_10a_main` (671,3 + 330,5 + 777,3 - 1 672,7 = 106,4), alors que la somme affichée est celle de l'arbre COFOG, GF0108 retiré.
- Correction : publier `ecart_consolidation_md = somme - total_consolide` (60,9) et, à part, `ecart_te_md` (106,3) avec sa définition ; ou afficher la phrase avec les deux TE.
- Test : `test_R28a_methode_administrations_ecart_egale_difference` (xfail I1).

**I2. Dépense fiscale « hors référence » comptée dans un programme.**
- Preuve : `niches/programmes.json`, programme 343, `fiscal_meur.2024` = 19 ; sa seule mesure, 920301, a `couts.2024.hors_reference: true` (contrat 2.18 : « hors totaux »). Somme des programmes 2024 = 89 425 M€ contre `niches/index.json` `totaux.2024.chiffre_meur` = 89 406 et `couverture.rattache_arbre_meur` = 89 406.
- Correction : `niches.py` exclut `hors_reference` des sommes par programme, mission et grand poste (comme pour les totaux) ; contrôle : somme des programmes + `hors_arbre` = `chiffre_meur`.
- Test : `test_R20f_niches_hors_reference_hors_totaux_des_programmes` (xfail I2).

**I3. Programme sans mesure chiffrée publié à 0 au lieu de `null`.**
- Preuve : `niches/programmes.json`, 12 couples programme-année avec `fiscal_meur` = 0 alors qu'aucune mesure n'est chiffrée et qu'au moins une est « nc » : 151 (mesure 070205 « nc » en 2024, 2025, 2026), 158 et 345 (2024 à 2026), 142 en 2024 (300201 « nc »), 305 et 101 en 2026. `non_chiffrees` le signale, mais le montant lu seul dit « 0 M€ ».
- Correction : `fiscal_meur.<année>` = `null` quand aucune mesure du programme n'est chiffrée et qu'au moins une est « nc » ; 0 reste juste quand toutes sont « - » (aucun effet budgétaire).
- Test : `test_R20g_niches_programme_sans_mesure_chiffree_jamais_zero` (xfail I3).

### Mineurs

| Id | Constat | Preuve (fichier : valeur) | Correction proposée | Test |
|---|---|---|---|---|
| M1 | La variante « nantes » est dite « commune du cas type C04 » ; C04 est à Lyon | `dette/interets.json` `cas_type.variantes.nantes.commune` = « 44109 (Nantes, commune du cas type C04 dans tests/cas_types) » ; `tests/cas_types/cas_types.json` C04 `commune_insee` = 69123 depuis sa création ; même phrase au contrat 2.19 | libellé « Nantes (variante de comparaison) » dans `dette.py` et au contrat | R14b (xfail) |
| M2 | Fixtures web de la dette antérieures aux données | `web/tests/fixtures/data/dette/interets.json` : `interets_sur_100_eur` 2,8, `total_annuel_eur` 13 781,38 (variante sans commune) ; publié : 2,79 et 13 891,95 | régénérer les fixtures `dette/` | R15b (xfail) |
| M3 | Deux destinataires Sécurité sociale de l'affectation sans nœud dans `secu/` | `prelevements/affectation.json` : `acoss` (TVA, 7,537 Md€), `msa_maladie`, `msa_vieillesse`, `msa_rco` (alcools, 4,131 Md€) ; absents de `secu/index.json` `liens_affectation.noeuds` | relier `acoss` à `robss` (répartition entre branches) et `msa_*` aux nœuds des régimes de base, ou le dire dans `liens_affectation` | R22b (xfail) |
| M4 | Le plafond « catégorie 32 (PLRG) » de la SCSP tracée est en réalité la part de catégorie 32 × montant de l'arbre | 23 programmes dépassent leur catégorie 32 PLRG : 159 (581,4 contre 486,7 M€, arbre +19 %), 103 (1 791,2 contre 1 770,3) ; chacun reste sous le plafond recalculé | corriger la docstring de `scsp_par_programme` et la phrase du contrat 2.14 | R16b (règle réelle) |
| M5 | Note des dotations communales inexacte ; 47 EPCI au total différent de leurs composantes | `local/dotations/communes/*.json` `note` : « (+ dotations des communes nouvelles) » ; 0 ligne sur 172 000 n'inclut `dgf_commune_nouvelle` (outre-mer : base + `dgf_dacom`). `epci.json` : 240500462 `dgf_totale` 1 095 564 contre 470 476 (80 M€ sur 5 ans, 47 EPCI) | réécrire la note ; publier l'écart EPCI comme composante « autre » | R24a (tolérance 0,5 %), R24b (xfail) |
| M6 | TVA : affectation et recettes d'origines différentes | `affectation.json` TVA 2025 = 210,0 Md€ (PLF et PLFSS 2026), part État 0,4805 ; `recettes.json` D211 2025 = 208,82 Md€, part État 0,4727 | citer l'écart dans la `note` de `tva` | R21b (tolérance 1 point, 2,5 Md€) |
| M7 | Deux séries Urssaf d'exonérations non rapprochées | `niches/sociales.json` `urssaf.totaux_meur.2024` = 80 631,0 (champ Urssaf) ; `controle/aides_entreprises.json` 2024 = 80 885,7 M€ (champ large) | renvoi croisé entre les deux fichiers avec la différence de champ | R30 (tolérance 0,5 %) |
| M8 | Détenteurs et encours de dette : 0,4 Md€ non expliqués | `dette/detenteurs.json` total 2025 = 3 460,5 ; `dette/encours.json` `eurostat.S13.md.2025` = 3 460,1 | ajouter l'écart à `ecarts[]` (gov_10dd_ggd contre edpt1) | R29 (tolérance 1 Md€) |
| M9 | Contribution comptable 2024 publiée deux fois | `ue/contribution.json` `contribution_comptable_2024_md` 24,3 (Sénat) ; `ue/retours.json` 2024 24,356 (retours - solde) | renvoyer l'un à l'autre | R08 (tolérance 0,1) |
| M10 | « Sur 100 € » de la vie politique sur un autre dénominateur | `vie_politique/annees.json` 2024 : 0,0768 sur 468,7 Md€ (budget général hors remboursements) ; règle `eur_sur_100` du contrat : arbre, 503,0 Md€, soit 0,0715 | documenté (`denominateur`, libellé « budget général ») ; mentionner l'exception au contrat 1 | R31 |
| M11 | `budget_meur` des missions et grands postes de `niches/programmes.json` = programmes porteurs de mesures seulement | « Engagements financiers de l'État » `budget_meur` 106 M€ contre 58 764,6 dans l'arbre ; `part_fiscale_2024` des missions surestimée | renommer en `budget_programmes_avec_mesures_meur` ou ajouter `budget_mission_arbre_meur` | R20d |
| M12 | Écran 3 : part empruntée calculée sur 511,1 Md€, affichée sur un total de 503,0 Md€ | `deficit.json` Exécution 2024 : dépenses nettes BG 443,41 + PSR 67,73 ; `arbre/racine.json` 502,96 | documenté (`etat.perimetre`) | R27 (tolérance 3 %) |
| M13 | COFOG et dépenses totales 2024 issues de deux tables Eurostat | `cofog.json` total 1 671,8 ; `administrations.json` 2024 Ensemble TE 1 672,7 | citer l'écart dans `methode.json` | R28b (tolérance 1,5 Md€) |

## 2. Points vérifiés sans écart

- **PSR-UE = contribution UE** : nœud `Prelevements sur recettes/Union européenne` 22,276394 Md€ = `ue/contribution.json` `psr_ue.md` = série exécutée 2024 = `ue/retours.json` = `tracabilite/noeud_psr_union_europeenne.json` ; LFI 2025 23,098 = `serie_psr_ue` vote 2025 ; `eur_sur_100` 4,43 = 22,276 / 502,96.
- **Charge de la dette** : programme 117 de l'arbre 49,267566 Md€ = `dette/interets.json` 2024 (49,268) = `realisations/117.json` = `meta.json` (`complements_plrg_md`) = `decisions/programme_117.json` ; part du 117 dans l'arbre 0,098.
- **SCSP opérateurs** : 34,249 Md€ en 2024 (171 lignes) ≤ catégorie 32 de `nature/` 34,345 Md€ ; LFI 2025 33,49 ≤ catégorie 32 du PLF 2025 35,29 ; SCSP tracée 33,34 ≤ 34,25.
- **Dotations et PSR collectivités** : DGF notifiée 2024 (communes 12,29, EPCI 6,39, départements 8,27, soit 26,95 Md€) ≤ PSR collectivités 45,46 Md€ ; DGF des comptes départementaux = DGF notifiée à 1 % près (384 couples).
- **Niches et arbre** : 545 mesures rattachées, `noeud_arbre` toujours un nœud programme de même code ; `budget_meur` = arbre ; totaux 2022-2024 = totaux DGFiP ; « nc », « ε », « - » toujours `null`, jamais 0, au niveau mesure.
- **Affectation et Sécurité sociale** : parts sourcées sommant à 1 ; destinataires de `liens_affectation` = nœuds portant `destinataire` ; taxe foncière par destinataire = `taxe_fonciere.json`.
- **Cas type 2 100 € net (C04, Lyon)** : `dette/interets.json` `fourchette_eur` = `web/affichage_lyon.json` (12 428,23 / 13 891,94 / 14 031,18) ; salaire et IR 7 638,36 € contre 7 638,37 € OpenFisca ; taxes sur la consommation = décile 5 central de `tva_conso.json` (6 143,01 €) ; TEOM = `taxe_fonciere/69.json` (110,57 €) ; « Plusieurs » = « autres taxes sur les produits » (1 504,69 €) ; sommes des parts 100,00.
- **Écran 3 « sur 100 € »** : pas de double compte. Les grands postes couvrent exactement la racine ; la liste « Et ce que tu verses ? » répartit le total du foyer une seule fois par administration (somme = total) ; seule la part État est ventilée au prorata des grands postes, PSR compris (transferts de l'État, pas une seconde comptabilisation de la part Collectivités). Les arbres Sécurité sociale (`secu/`) ne sont jamais additionnés à l'arbre État.
- **Traçabilité** : 135 nœuds, parts sommant au total et à 100 %, total = arbre, résumé = somme des nœuds ; seule part négative : programme 423 (net négatif, rangé en entier dans `non_publie`, règle du contrat).
- **Déficit** : formules du solde et de la part empruntée vérifiées pour les quatre vues ; APU = `administrations.json` ; `meta.json` = `deficit.json`.

## 3. Règles et tests

| Règle | Contrôle | Test |
|---|---|---|
| R01 | chaque nœud des trois arbres État = somme de ses enfants, sous-fichiers compris | `test_R01_*` |
| R02 | racine = programmes + PSR ; `meta.json` = arbre | `test_R02_*` |
| R03 | sankey : conservation par niveau, `total_net_arbre`, liens `psr:` = arbre | `test_R03_*` |
| R04-R10 | Union européenne : PSR, série, retours, rubriques, engagements | `test_R04_*` à `test_R10_*` |
| R11-R13 | dette : programme 117 sur cinq fichiers, part anonyme, cas type interne | `test_R11_*` à `test_R13_*` |
| R14-R15 | cas type C04 : pipeline, OpenFisca, données, web, fixtures | `test_R14*`, `test_R15*` |
| R16-R19 | SCSP, nature, bénéficiaires, traçabilité | `test_R16*` à `test_R19_*` |
| R20 | dépenses fiscales : null, totaux, rattachement, sommes par programme, coûts hors référence, programme non chiffré | `test_R20a_*` à `test_R20g_*` |
| R21-R22 | affectation, TVA, déciles, taxe foncière, liens Sécurité sociale | `test_R21*`, `test_R22*` |
| R23-R24 | DGF et PSR collectivités, composantes, comptes et notifications | `test_R23_*`, `test_R24*` |
| R25 | décisions = réalisations (PLRG) pour chaque programme, null avec raison, conformité JO/PLRG selon la tolérance publiée | `test_R25*` |
| R26-R28 | déficit, écran 3, administrations, COFOG, recettes | `test_R26_*` à `test_R28*` |
| R29-R31 | détenteurs et encours, contrôle (Urssaf, France 2030), vie politique | `test_R29_*` à `test_R31_*` |
| R32-R33 | `null` propagé (effectifs, trous de la dette) | `test_R32_*`, `test_R33_*` |

Hors champ de ce fichier (déjà couverts ailleurs) : conformité aux schémas (`test_contrat.py`), personnes physiques (`test_confidentialite.py`), conservation des groupes de bénéficiaires et contrôles internes de chaque producteur (`test_<producteur>.py`).

Capital utilisé : tests et validateur existants du dépôt (`tests/`, `docs/valider_contrat.py`) réutilisés tels quels ; corrections faites dans les pipelines existants avec leurs commandes `collecter` et `produire` ; recherche publique sans objet (contrôle interne de données déjà produites, aucun outil externe nécessaire).
