# Vérification des grands totaux face aux chiffres officiels

Vérification du 19/11/2026. Question : chaque grand total affiché par le site est-il égal au chiffre officiel publié, sans double compte ni oubli ?
Le contrôle est permanent : `tests/test_totaux_officiels.py` relit la table versionnée `docs/references_officielles.json` (valeur officielle, document, tableau, millésime, URL, tolérance justifiée) à chaque passage de `pytest` (workflow `.github/workflows/verifier.yml`, job « Donnees »), sans réseau. La répartition « sur 100 € » du simulateur est contrôlée par `web/tests/sur100_totaux.test.ts` (job « Site »).

## 1. Méthode

1. Inventaire des grands totaux affichés (grand chiffre d'un écran, total d'un arbre, total d'une série publiée à l'écran).
2. Pour chacun : valeur du site (fichier et champ de `site/data`), valeur officielle lue dans le document source, écart absolu et relatif.
   Sources relues le 19/11/2026 : situation mensuelle budgétaire et textes législatifs de la DGFiP (copies versionnées `data/raw/`), PLRG 2024, PLACSS 2024 et 2025 (texte des articles 1 et 2, Assemblée nationale, téléchargés et contrôlés par `collecte/integrite.py`), Eurostat (`gov_10a_main`, `gov_10a_exp`, `gov_10a_taxag`, `gov_10dd_edpt1`, mises à jour d'octobre et novembre 2026), Insee BDM (dette trimestrielle, base 2020) et Insee DD_CNA_APU (31/08/2026), bases OFGL (régions, départements), Évaluation des voies et moyens tome II du PLF 2026 (p. 17), annexe « Opérateurs de l'État » du PLF 2026, notes du Sénat « Affaires européennes » PLF 2026 et 2027 (motifs déjà vérifiés par `pipeline/ue.py`).
3. Classe de chaque total : **conforme** (écart inférieur ou égal à la tolérance), **écart expliqué** (périmètre, méthode ou année : l'écart est décomposé en montants publiés et le test vérifie la décomposition), **erreur corrigée**, **non vérifiable** (aucun chiffre officiel publié).
4. Un écart de périmètre n'est pas une erreur : il est écrit à l'écran près du total quand le visiteur peut comparer au chiffre officiel (phrase courte, neutre, avec la source), sans chiffre calculé (règle 13).

## 2. Résultat par classe

| Classe | Totaux |
|---|---|
| conforme | 47 |
| ecart_explique | 6 |
| erreur_corrigee | 2 |
| non_verifiable | 1 |

## 3. Inventaire

Montants en Md€ sauf dépenses fiscales (M€) et dette en % du PIB. Écart = site moins officiel. Les arbres de l'État sont comparés hors prélèvements sur recettes (le total affiché les inclut : 502,96 Md€ en exécution 2024, 502,97 Md€ en LFI 2025, 509,67 Md€ en exécution 2025 ; les prélèvements sur recettes sont conformes à la situation budgétaire).

| Identifiant | Total | Site | Officiel | Écart | Classe |
|---|---|---|---|---|---|
| `etat_solde_budgetaire_execution_2024` | Solde budgétaire de l'État, exécution 2024 | -155,9300 | -155,9300 | -0,0000 (+0,00 %) | conforme |
| `etat_solde_budgetaire_execution_2025` | Solde budgétaire de l'État, exécution 2025 | -124,2057 | -124,2057 | -0,0000 (+0,00 %) | conforme |
| `etat_solde_budgetaire_lfi_2025` | Solde budgétaire de l'État voté, LFI 2025 | -138,9959 | -138,9959 | -0,0000 (+0,00 %) | conforme |
| `etat_solde_budgetaire_lfi_2024` | Solde budgétaire de l'État voté, LFI 2024 | -146,8915 | -146,8915 | -0,0000 (+0,00 %) | conforme |
| `etat_depenses_nettes_bg_execution_2024` | Dépenses nettes du budget général, exécution 2024 | 443,4133 | 443,4133 | 0,0000 (+0,00 %) | conforme |
| `etat_recettes_nettes_bg_execution_2024` | Recettes nettes du budget général, exécution 2024 | 348,8909 | 348,8909 | -0,0000 (-0,00 %) | conforme |
| `etat_psr_execution_2024` | Prélèvements sur recettes, exécution 2024 | 67,7332 | 67,7332 | -0,0000 (-0,00 %) | conforme |
| `etat_psr_collectivites_execution_2024` | Prélèvement sur recettes au profit des collectivités, exécution 2024 | 45,4568 | 45,4568 | -0,0000 (-0,00 %) | conforme |
| `etat_remboursements_degrevements_execution_2024` | Remboursements et dégrèvements d'impôts retirés de l'arbre, exécution 2024 | 146,5235 | 146,5235 | 0,0000 (+0,00 %) | conforme |
| `etat_arbre_execution_2024` | Total de l'arbre de l'État hors prélèvements sur recettes, Exécution 2024 | 435,2304 | 443,4133 | -8,1829 (-1,85 %) | ecart_explique |
| `etat_arbre_lfi_2025` | Total de l'arbre de l'État hors prélèvements sur recettes, LFI 2025 | 434,6381 | 438,8202 | -4,1821 (-0,95 %) | ecart_explique |
| `etat_arbre_execution_2025` | Total de l'arbre de l'État hors prélèvements sur recettes, Exécution 2025 | 440,6340 | 441,1943 | -0,5603 (-0,13 %) | ecart_explique |
| `secu_robss_2024` | Dépenses des régimes obligatoires de base et du FSV (hors transferts), exécution 2024 | 643,1000 | 643,1000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_maladie_2024` | Branche maladie, exécution 2024 | 253,0000 | 253,0000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_atmp_2024` | Branche AT-MP, exécution 2024 | 16,3000 | 16,3000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_vieillesse_2024` | Branche vieillesse, exécution 2024 | 293,8000 | 293,8000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_famille_2024` | Branche famille, exécution 2024 | 57,8000 | 57,8000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_autonomie_2024` | Branche autonomie, exécution 2024 | 39,9000 | 39,9000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_fsv_2024` | Fonds de solidarité vieillesse, exécution 2024 | 20,4570 | 20,5000 | -0,0430 (-0,21 %) | conforme |
| `secu_robss_2025` | Dépenses des régimes obligatoires de base et du FSV (hors transferts), exécution 2025 | 666,0000 | 666,0000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_maladie_2025` | Branche maladie, exécution 2025 | 262,6000 | 262,6000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_atmp_2025` | Branche AT-MP, exécution 2025 | 17,4000 | 17,4000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_vieillesse_2025` | Branche vieillesse, exécution 2025 | 304,1000 | 304,1000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_famille_2025` | Branche famille, exécution 2025 | 58,5000 | 58,5000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_autonomie_2025` | Branche autonomie, exécution 2025 | 41,8000 | 41,8000 | 0,0000 (+0,00 %) | conforme |
| `secu_robss_fsv_2025` | Fonds de solidarité vieillesse, exécution 2025 | 21,4000 | 21,4000 | 0,0000 (+0,00 %) | conforme |
| `secu_cades_dette_amortie_2024` | Dette sociale amortie par la CADES, 2024 | 15,9886 | 16,0000 | -0,0114 (-0,07 %) | conforme |
| `secu_cades_dette_amortie_2025` | Dette sociale amortie par la CADES, 2025 | 16,2000 | 16,2000 | 0,0000 (+0,00 %) | conforme |
| `secu_total_organismes_2024` | Total de l'arbre « dépenses des organismes », exécution 2024 | 827,9156 | 643,1000 | 184,8156 (+28,74 %) | ecart_explique |
| `secu_total_organismes_2025` | Total de l'arbre « dépenses des organismes », exécution 2025 | 727,4750 | 666,0000 | 61,4750 (+9,23 %) | erreur_corrigee |
| `apu_depenses_2024` | Dépenses des administrations publiques (TE), 2024 | 1 672,7000 | 1 672,7082 | -0,0082 (-0,00 %) | conforme |
| `apu_depenses_2025` | Dépenses des administrations publiques (TE), 2025 | 1 714,1000 | 1 714,1117 | -0,0117 (-0,00 %) | conforme |
| `apu_recettes_2024` | Recettes des administrations publiques (TR), 2024 | 1 503,6000 | 1 503,5901 | 0,0099 (+0,00 %) | conforme |
| `apu_solde_2024` | Besoin de financement des administrations publiques (B9), 2024 | -169,1000 | -169,1181 | 0,0181 (-0,01 %) | conforme |
| `apu_solde_2025` | Besoin de financement des administrations publiques (B9), 2025 | -151,6000 | -151,5920 | -0,0080 (+0,01 %) | conforme |
| `apul_depenses_2025` | Dépenses des administrations publiques locales (S1313), 2025 | 335,5000 | 335,4818 | 0,0182 (+0,01 %) | conforme |
| `asso_depenses_2025` | Dépenses des administrations de sécurité sociale (S1314), 2025 | 803,2000 | 803,1640 | 0,0360 (+0,00 %) | conforme |
| `cofog_total_2024` | Dépenses publiques par fonction (COFOG), total 2024 | 1 671,8000 | 1 671,7938 | 0,0062 (+0,00 %) | conforme |
| `tva_2025` | Taxes du type TVA (D211), toutes administrations, 2025 | 208,8200 | 208,8210 | -0,0010 (-0,00 %) | conforme |
| `interets_apu_2025` | Intérêts versés par les administrations publiques (D41), 2025 | 65,7210 | 65,7209 | 0,0001 (+0,00 %) | conforme |
| `dette_maastricht_2024` | Dette de Maastricht fin 2024 | 3 306,1000 | 3 306,1000 | 0,0000 (+0,00 %) | conforme |
| `dette_maastricht_2025` | Dette de Maastricht fin 2025 | 3 460,1000 | 3 460,1000 | 0,0000 (+0,00 %) | conforme |
| `dette_maastricht_pct_pib_2025` | Dette de Maastricht fin 2025, en % du PIB | 115,7000 | 115,7000 | 0,0000 (+0,00 %) | conforme |
| `dette_maastricht_2026T2` | Dette de Maastricht au 2e trimestre 2026 | 3 595,5000 | 3 595,5000 | 0,0000 (+0,00 %) | conforme |
| `regions_depenses_2025` | Dépenses totales des régions et collectivités à statut particulier, 2025 | 42,1972 | 42,1972 | -0,0000 (-0,00 %) | erreur_corrigee |
| `departements_depenses_2025` | Dépenses totales des départements (y compris Paris et la métropole de Lyon), 2025 | 95,8287 | 95,8287 | 0,0000 (+0,00 %) | conforme |
| `ue_psr_execution_2024` | Prélèvement sur recettes au profit de l'UE, exécution 2024 | 22,2764 | 22,2764 | 0,0000 (+0,00 %) | conforme |
| `ue_psr_execution_2025` | Prélèvement sur recettes au profit de l'UE, exécution 2025 | 22,9610 | 22,9617 | -0,0007 (-0,00 %) | conforme |
| `ue_retours_2024` | Dépenses de l'UE réalisées en France (retours), 2024 | 16,4560 | 16,4560 | 0,0000 (+0,00 %) | conforme |
| `ue_solde_net_2024` | Solde net comptable de la France, 2024 | -7,9000 | -7,9000 | 0,0000 (-0,00 %) | conforme |
| `ue_contribution_comptable_2024` | Contribution totale de la France (méthode comptable), 2024 | 24,3000 | 24,3000 | 0,0000 (+0,00 %) | conforme |
| `niches_total_2024` | Dépenses fiscales chiffrées, 2024 (grand chiffre de l'écran) | 89 406,0 | 89 406,0 | 0,0000 (+0,00 %) | conforme |
| `niches_total_2025` | Somme des dépenses fiscales chiffrées, 2025 (estimation) | 88 932,0 | 91 834,0 | -2 902,0000 (-3,16 %) | ecart_explique |
| `niches_total_2026` | Somme des dépenses fiscales chiffrées, 2026 (estimation) | 79 613,0 | 88 269,0 | -8 656,0000 (-9,81 %) | ecart_explique |
| `operateurs_scsp_execution_2024` | Subventions pour charges de service public versées aux opérateurs, exécution 2024 | 34,2489 | aucun publié | sans objet | non_verifiable |
| `simulateur_sur_100` | Répartition « sur 100 € » du simulateur (Sécurité sociale, État, collectivités, sans destinataire publié) | par foyer | aucun publié | sans objet | conforme |

## 4. Écarts expliqués

| Total | Explication (composantes publiées, vérifiées par le test) | À l'écran |
|---|---|---|
| `etat_arbre_execution_2024` | -8,18 Md€ = -4,96 (remboursements et dégrèvements d'impôts locaux, compris dans les dépenses nettes du budget général, retirés de l'arbre) -7,20 (budget vert retraité au format PLF 2026 face au PLRG) +3,98 (avances à l'audiovisuel public, compte de concours financiers gardé). | Écran État : « Ce total n'est pas un chiffre publié tel quel… Chiffres officiels de la même année : dépenses nettes du budget général 443,41 Md€, prélèvements sur recettes 67,73 Md€ (situation budgétaire de l'État au 31 décembre 2024, DGFiP) » ; bloc « Deux méthodes » et écran Méthode pour le retraitement. |
| `etat_arbre_lfi_2025` | -4,18 Md€ = -4,73 (dégrèvements locaux) -3,40 (retraitement) +3,95 (audiovisuel public). | Même phrase, « loi de finances initiale pour 2025 ». |
| `etat_arbre_execution_2025` | -0,56 Md€ = -4,52 (dégrèvements locaux) +3,96 (audiovisuel public) ; pas de retraitement (lecture directe du PLRG 2025). | Même phrase, situation au 31 décembre 2025. |
| `secu_total_organismes_2024` | +184,82 Md€ = régimes complémentaires 120,20 + Unédic 45,20 + CADES 19,41 ajoutés aux régimes obligatoires de base et au FSV (643,1 Md€, PLACSS 2024). | Avertissement de la racine de l'arbre Sécurité sociale : « Ce total n'est pas un chiffre publié… 643,1 Md€ (PLACSS 2024, article 1) ». |
| `niches_total_2025` | -2 902 M€ : le total publié impute une prévision aux mesures « nc », le site ne compte jamais une mesure non chiffrée. | Écran Dépenses fiscales : colonne « Total publié » et phrase sous le tableau (`ecart_explication`). |
| `niches_total_2026` | -8 656 M€, même cause. | Idem. |

Retraitement du budget vert (2024) : l'écart de 7,20 Md€ avec le PLRG se concentre sur quelques programmes (203 Infrastructures et services de transports -4,17 ; 345 Service public de l'énergie -3,17 ; 174 Énergie, climat et après-mines -1,38 ; 135 Urbanisme +1,35 ; programmes 841 à 845 de l'audiovisuel public, nouveaux au format PLF 2026). La source ne détaille pas ce retraitement programme par programme : il reste publié comme écart de méthode (`millesimes/index.json`, rubrique « comparaison »), et l'exécution 2025 se lit directement dans le PLRG.

Autres écarts déjà publiés par le site et vérifiés sans changement : COFOG 1 671,8 Md€ face aux dépenses totales 1 672,7 Md€ (deux tables Eurostat, `docs/QUALITE.md` M13) ; intérêts 2025 Eurostat 65,7 Md€ face à Insee 67,5 Md€ (`dette/index.json`) ; besoin de financement 2025 : -151,6 Md€ (Eurostat, notification d'octobre 2026, retenu par le site) contre -152,5 Md€ dans le fichier Insee DD_CNA_APU du 31/08/2026, antérieur à la révision.

## 5. Erreurs corrigées

| Total | Avant | Après | Commit |
|---|---|---|---|
| `secu_total_organismes_2025` | La vue Exécution 2025 reprenait l'avertissement 2024 : 2,7 Md€ comptés deux fois (Unédic vers Agirc-Arrco 2,5 ; FSV vers régimes complémentaires 0,2), alors que cette vue n'a pas de régimes complémentaires ; 727,5 Md€ présentés sans mise en garde face aux 827,9 Md€ de 2024. | Aucun double compte cité pour 2025 ; avertissement : périmètre sans régimes complémentaires, non comparable à 2024 ; chiffre officiel le plus proche 666,0 Md€ (PLACSS 2025). Montants inchangés. | `secu : avertissement propre à chaque vue…` (pipeline/secu.py) |
| `regions_depenses_2025` | « Les 18 régions : 42,2 Md€ » : la somme porte sur 17 comptes OFGL (Mayotte est dans la base des départements). | « Les régions et collectivités à statut particulier (17 comptes publiés par l'OFGL ; Mayotte est comptée avec les départements) : 42,2 Md€ » avec le badge « calculé par le site » et sa méthode ; départements : 97 comptes, dont Paris et la métropole de Lyon, même badge. Montants inchangés. | `collectivites : nombre de comptes réellement sommés…` (web/src/ecrans/collectivites.ts) |

Aucun montant publié n'a été trouvé faux : les 47 totaux conformes sont égaux au chiffre officiel à l'arrondi près.

## 6. Non vérifiable

`operateurs_scsp_execution_2024` (34,25 Md€) : l'annexe « Opérateurs de l'État » du PLF 2026 publie l'exécution 2024 opérateur par opérateur, sans total ; ses tableaux de synthèse (p. 17 à 24) ne totalisent que la LFI 2025 (33 491 513 097 €) et le PLF 2026. Le site affiche une somme calculée : badge « calculé par le site » et méthode ajoutés (règle 13), avec la phrase « Ce total n'est pas publié tel quel ». Contrôle secondaire, non affiché : la somme des lignes LFI 2025 lues (33,488 Md€) est inférieure de 3,2 M€ (0,01 %) au total publié.

## 7. Cohérence interne

| Contrôle | Résultat | Test |
|---|---|---|
| Somme des parties égale au tout, arbres de l'État (exécution 2024, LFI 2025, nature PLF 2025) et sankey | aucun écart | `test_coherence.py` R01 à R03 |
| Somme des parties égale au tout, toutes les autres racines publiées (Sécurité sociale 2024 et 2025, protection sociale DREES, administrations, exécution 2025) | aucun écart | `test_totaux_officiels.py::test_somme_des_enfants_egale_le_noeud` |
| Transferts de l'État aux collectivités et à l'Union européenne : un seul nœud « prélèvements sur recettes », égal à la situation budgétaire | conforme | `test_psr_collectivites_et_ue_une_seule_fois_dans_l_arbre_etat`, R02, R04 à R06 |
| Vue consolidée des administrations publiques : ensemble inférieur à la somme des sous-secteurs (transferts comptés une fois), soldes additifs | conforme, 2005 à 2025 | `test_administrations_consolidees_transferts_comptes_une_fois`, R28 |
| Sécurité sociale : transferts entre branches et avec le FSV déduits (nœud négatif, 38,2 Md€ en 2024, 39,8 Md€ en 2025) ; doubles comptes restants publiés (2,7 Md€ en 2024) | conforme après correction | avertissements de `pipeline/secu.py` |
| DGF et compensations : DGF notifiée dans le prélèvement sur recettes collectivités, totaux DGF égaux à leurs composantes | conforme (écarts EPCI publiés) | R23, R24 |
| Opérateurs : total affiché égal au total de l'index | conforme | `test_operateurs_total_affiche_egal_index` |
| « Sur 100 € » du simulateur : somme des administrations égale au total payé (ventilations de somme 1 à un millionième près), euros entiers totalisant 100 | conforme pour les 44 cas types | `web/tests/sur100_totaux.test.ts` |
| ITAF (impositions de toute nature affectées) : TVA affectée face aux recettes Eurostat | écart publié (M6) | R21b |

## 8. Constats laissés au propriétaire (règle 13, hors correction)

- Écran Dépenses fiscales : « l'équivalent de X sur 100 € de dépense du budget de l'État » rapporte des moindres recettes (dépenses fiscales 2024) aux dépenses de l'arbre 2024 : même année, mais périmètres différents, sans badge ni méthode.
- Écran État : la part empruntée est calculée sur les dépenses nettes du budget général plus les prélèvements sur recettes (511,1 Md€ en 2024) et affichée sur l'arbre (502,96 Md€) ; le site l'écrit (« ordre de grandeur », `docs/QUALITE.md` M12), mais la règle 13 demande le même périmètre.

## 9. Mettre à jour

Nouveau millésime officiel : relire le document source, mettre à jour `valeur`, `millesime` et `url` de l'entrée (ou en ajouter une), relancer `pytest tests/test_totaux_officiels.py`. Un total qui s'écarte de sa référence après une régénération est une erreur de pipeline à corriger, ou une révision de la source à citer : jamais une tolérance élargie sans justification écrite.

## 10. Règle n°0 (existant)

- Dans le dépôt : `tests/test_coherence.py` et `docs/QUALITE.md` (cohérence interne, réutilisés tels quels et complétés), `collecte/integrite.py` (contrôle des téléchargements), `pipeline/secu.py collecter` (sources de la Sécurité sociale), `badgeCalcule` (web/src/util.ts).
- Recherche publique (19/11/2026) : aucun jeu ni dépôt ne publie une table de rapprochement des grands agrégats des finances publiques entre producteurs ; les producteurs publient chacun leurs agrégats (DGFiP, DSS, Insee, Eurostat, OFGL), lus ici directement. Verdict : inspiration seulement pour la forme (tables de référence de tests de régression) ; aucune réutilisation de code.
