# Schémas à reporter dans le contrat d'interface (nature, effectifs, bénéficiaires)

Proposition pour la version **1.1** du contrat (ajout de fichiers, rien de renommé). Producteur : `pipeline/beneficiaires.py`. Tous les montants sont en **euros** (pas en Md€) ; `eur_sur_100` = montant / total de l'arbre État (`arbre/racine.json`, exécution 2024) × 100, à lire « X € sur 100 € du budget de l'État ». Tous les fichiers portent `millesime` et `source`.

```
data/lake (PLRG 2024, ETPT LFI 2023, jaune associations PLF 2025, jaune opérateurs PLF 2025, France 2030, DECP)
   + API Recherche d'entreprises (catégorie juridique, cache data/lake/_cache/)
        └─> pipeline/beneficiaires.py ─> site/data/nature/  site/data/effectifs/  site/data/beneficiaires/
```

Commandes : `python pipeline/beneficiaires.py resoudre associations france2030 acheteurs titulaires` (réseau, reprenable, `--budget` secondes), puis `python pipeline/beneficiaires.py tout` (sans réseau). Tests : `pytest tests/test_beneficiaires.py`.

## Règle personnes physiques (bloquante)

Seules les personnes morales sont nommées : catégorie juridique `2xxx` à `9xxx`, lue dans la source ou via l'API. Tout objet portant `siren` porte aussi `categorie_juridique` conforme. Aucun champ ne contient « prénom ». Le reste est agrégé dans `exclus_personnes_physiques_ou_non_identifies` (entrepreneurs individuels `1000`, SIREN absent ou invalide comme « NR CHORUS », catégorie introuvable) ou dans `autres_non_verifies` (SIREN valide pas encore vérifié). Le CSV `beneficiaires/beneficiaires_publies.csv` est validé par Frictionless (`datapackage.json`, motif `^[2-9][0-9]{3}$`).

## Groupe de bénéficiaires (structure commune)

Conservation : `somme(top.montant_eur) + autres_personnes_morales.montant_eur + autres_non_verifies.montant_eur + exclus_personnes_physiques_ou_non_identifies.montant_eur = total` (à 1 € près).

| Champ | Type | Sens |
|---|---|---|
| `top` | tableau (≤ 50), trié par montant décroissant | bénéficiaires nommés |
| `top[].siren` | chaîne `^[0-9]{9}$` | SIREN de la personne morale |
| `top[].denomination` | chaîne | dénomination (source ou SIRENE) |
| `top[].categorie_juridique` | chaîne `^[2-9][0-9]{3}$` | catégorie juridique INSEE |
| `top[].montant_eur` | nombre | montant reçu |
| `top[].eur_sur_100` | nombre | associations et France 2030 seulement |
| `autres_personnes_morales` | `{nombre, montant_eur}` | personnes morales au-delà du top 50 |
| `autres_non_verifies` | `{nombre, montant_eur, note}` | SIREN valides non vérifiés, jamais nommés |
| `exclus_personnes_physiques_ou_non_identifies` | `{montant_eur, lignes, dont_...}` | montant agrégé exclu ; `dont_personnes_physiques_eur` et selon la source `dont_siren_nr_chorus_eur`, `dont_sans_siren_eur`, `dont_identifiant_non_siret_eur`, `dont_categorie_inconnue_eur` |

## `nature/<programme>.json`

Nature réelle de la dépense 2024 (PLRG 2024, annexe 1 « titre × catégorie », dépenses constatées). Un fichier par programme du PLRG (126).

| Champ | Type | Sens |
|---|---|---|
| `millesime` | `"Exécution 2024"` | |
| `programme`, `libelle`, `mission` | chaînes | `programme` sur 3 chiffres |
| `total_eur`, `eur_sur_100` | nombres | total du programme |
| `postes[]` | `{id, libelle, categories[], eur, part_programme_pct, eur_sur_100}` | regroupement lisible ; `id` parmi `salaires` (21), `cotisations` (22), `prestations_employeur` (23), `fonctionnement` (31), `subventions_operateurs` (32), `interventions_menages` (61), `interventions_entreprises` (62), `interventions_collectivites` (63), `interventions_autres` (64), `appels_garantie` (65), `investissement` (51 à 53), `dette` (41 à 43), `pouvoirs_publics` (10), `operations_financieres` (71 à 73) |
| `categories[]` | `{code, libelle, eur}` | catégories LOLF brutes |
| `controle_arbre` | `{millesime_arbre, total_arbre_eur, ecart_eur, ecart_pct, explication}` | écart avec le nœud programme de l'arbre ; `null` si le programme n'est pas dans l'arbre (200, 201) |

Contrôle : la somme des programmes présents dans l'arbre s'écarte de l'arbre de `controle.nature.ecart_global_pct` (1,93 %) ; tolérance publiée `controle.nature.tolerance_pct` = 3 % (`beneficiaires/index.json`). Les écarts par programme viennent des retraitements du budget vert (fonds de concours, périmètre 2026) : par exemple 203 (+94 %), 345 (+125 %), 135 (−53 %).

## `effectifs/<programme>.json`

| Champ | Type | Sens |
|---|---|---|
| `etpt`, `millesime_etpt` | nombre ou `null`, `"LFI 2023"` | plafond d'emplois voté, dernier millésime publié par programme |
| `categories_emploi[]` | `{categorie_emploi, etpt}` | |
| `titre2_eur`, `millesime_titre2` | nombre, `"Exécution 2024"` | catégories 21 + 22 + 23 du PLRG 2024 |
| `eur_sur_100_titre2` | nombre | |
| `cout_moyen_par_etpt_eur` | entier ou `null` | `titre2_eur / etpt` (coût complet employeur, pensions comprises) |
| `avertissement` | chaîne ou `null` | millésimes différents ; programme sans ETPT publié |

## `beneficiaires/programme_<n>.json`

| Champ | Type | Sens |
|---|---|---|
| `programme`, `libelle`, `mission`, `dans_arbre` | | rattachement à l'arbre |
| `programme_arbre_eur`, `programme_eur_sur_100` | nombres ou `null` | taille du programme dans l'arbre 2024 |
| `associations` | objet ou `null` | groupe de bénéficiaires + `millesime` (« Crédits versés en 2023 »), `source`, `total_source_eur`, `lignes_source`, `personnes_morales`, `eur_sur_100` ; `top[]` ajoute `objet` et `lignes` |
| `operateurs` | objet ou `null` | `{millesime: "PLF 2025", source, note, nombre, liste[{operateur, categorie, statut}]}`, opérateurs dont le programme est chef de file, sans montant (la source n'en donne pas) |

## `beneficiaires/france2030.json`

`millesime` : projets décidés de 2021 à 2025 (montants engagés cumulés, subvention + avance remboursable). `lignes_source`, `doublons_exacts_retires`. `ensemble` et `par_operateur.<Bpifrance|ANR|ADEME|Caisse des Dépôts|DGAC|CNES>` : groupe de bénéficiaires + `total_eur`, `projets`, `beneficiaires_personnes_morales` ; `top[]` ajoute `typologie`, `operateurs[]`, `projets`. `par_programme.<424|425>` : `{total_eur, projets, libelle}` (rattachement par le code action de la source).

## `beneficiaires/marches_etat.json`

`millesime` : marchés notifiés en 2024. Périmètre : acheteurs de catégorie juridique `71xx` (services de l'État). `ensemble` et `par_ministere.<ministère>` (dont « État, ministère non identifié ») : groupe de bénéficiaires + `total_eur`, `nombre_marches` ; `top[]` ajoute `nombre_marches`. `ecartes_montants_aberrants` : `{montant_eur, lignes}`. Rattachement au ministère d'après le nom SIRENE de l'acheteur (le programme n'existe pas dans les DECP).

## `beneficiaires/index.json`

`programmes[]` (numéros), `fichiers` (chemins relatifs à `site/data/`), `regle_personnes_physiques`, `controle` (totaux et écarts de chaque étape, dont `controle.nature.tolerance_pct`).

## Tables Frictionless (`datapackage.json`)

`site/data/beneficiaires/beneficiaires_publies.csv` (source, groupe, siren, denomination, categorie_juridique, montant_eur), `site/data/nature/nature_2024.csv` (programme, categorie, libelle_categorie, eur), `site/data/effectifs/effectifs.csv` (programme, etpt_lfi_2023, titre2_execution_2024_eur, cout_moyen_par_etpt_eur).
