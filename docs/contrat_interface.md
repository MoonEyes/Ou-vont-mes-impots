# Contrat d'interface pipeline / site

Version du contrat : **1.4** (17/11/2026).

| Version | Date | Changement |
|---|---|---|
| 1.0 | 15/11/2026 | fichiers budget de l'État, Eurostat, communes ; module de calcul personnel |
| 1.1 | 15/11/2026 | précision par programme : `nature/`, `effectifs/`, `beneficiaires/` |
| 1.2 | 16/11/2026 | bloc « Ce qui a été fait » : `realisations/` |
| 1.3 | 17/11/2026 | `vie_politique/` ; schémas 1.0 alignés sur les fichiers réellement produits (en-tête `millesime`/`source`, enveloppe `communes`, `deficit.json` État et APU, nœuds `psr:` du sankey, montants d'exécution négatifs, arbres LFI 2025 et nature PLF 2025) |
| 1.4 | 17/11/2026 | `prelevements/` : affectation sourcée de chaque prélèvement, taxes sur la consommation par décile, taxe foncière estimée par commune |

Ce document fixe ce que le pipeline (`pipeline/`) écrit dans `site/data/` et ce que le site lit, ainsi que le format d'entrée et de sortie du module de calcul personnel (exécuté dans le navigateur). Chaque format a son JSON Schema dans `docs/schemas/` ; les définitions partagées (en-tête, SIREN, groupe de bénéficiaires) sont dans `commun.schema.json`. Le schéma fait foi en cas de doute ; ce document en donne le sens.

```
data/raw (fetch.py) ──> transform.py ───────────────> site/data/ (budget, Eurostat, communes, meta.json)
data/lake (collecte/) ─> beneficiaires.py ─> realisations.py ─> vie_politique.py ─> tracabilite.py, prelevements.py
                                    └──────────────> site/data/ (nature, effectifs, beneficiaires, realisations, ...)
                                                          │
                              docs/valider_contrat.py (docs/schemas/*.schema.json) ──> site (lecture)

profil saisi ──> module de calcul (modele-social + publicodes) ──> résultat ou erreur
                                   └─> recoupement OpenFisca (optionnel) ─┘
```

Vérification : `python docs/valider_contrat.py` (installe `jsonschema` si absent ; `pytest tests/test_contrat.py` le lance). Code de sortie 1 si un fichier présent est non conforme ou si un fichier existant manque ; un fichier « prévu » absent est seulement signalé. Contrôles hors schéma : liens `fichier` (arbres, index), conservation des groupes de bénéficiaires à 1 € près. Un JSON de `site/data` couvert par aucun schéma est signalé `ORPHELIN` (bloquant avec `--strict`, et toujours bloquant dans les tests pour un fichier versionné).

## 1. Règles communes

| Règle | Valeur |
|---|---|
| Encodage | UTF-8, JSON compact (sauf `meta.json`, indenté) |
| En-tête | tout fichier JSON de `site/data` porte `millesime` (chaîne lisible, ex. `"Exécution 2024"`) et `source` (jeu et pièce d'origine) ; souvent aussi `unite` et `avertissement`. `meta.json` fait exception : `millesime` y est un objet |
| Chemins | relatifs à `site/data/` (ex. `"fichier": "arbre/Culture-et-medias_Culture_131.json"`). Écart connu : `vie_politique/annees.json` écrit ses liens relatifs à `vie_politique/` (`"partis/2012.json"`) ; le validateur l'accepte, à aligner à la prochaine version majeure |
| Montants agrégés | milliards d'euros (`md`) pour le budget de l'État et Eurostat ; euros (`*_eur`) pour les fichiers par programme (nature, effectifs, bénéficiaires, réalisations, vie politique). Le champ `unite` du fichier le rappelle |
| `eur_sur_100` | montant / total de l'arbre État (`arbre/racine.json`, exécution 2024) × 100, à lire « X € sur 100 € du budget de l'État » |
| Montants personnels | euros par an, positifs = montant prélevé ; le site affiche le mensuel = annuel / 12 |
| Années | chaînes `"2025"` dans les clés JSON et les fichiers 1.0 ; entiers (`annee`, `exercice`) dans les fichiers 1.2 et 1.3 et dans le module de calcul |
| Administrations | libellés exacts, sans accent : `Ensemble`, `Etat`, `Collectivites locales`, `Securite sociale` (secteurs S13, S1311, S1313, S1314 ; l'État inclut les organismes divers d'administration centrale) |
| Absence | `null` = donnée absente à la source, jamais 0 ; une clé absente = niveau non applicable |
| Personnes physiques | seules les personnes morales sont nommées (catégorie juridique `2xxx` à `9xxx`) ; aucun champ ne contient « prénom ». Seule exception : les candidats des comptes de campagne publiés par la CNCCFP ou au Journal officiel, avec une liste blanche de champs (2.11) |
| Traçabilité | chaque montant publié remonte à un jeu public nommé dans `source` ; un montant écarté (remboursements, hors périmètre, aberrant) est publié avec sa raison, jamais supprimé en silence |
| Évolution | ajout d'un champ facultatif ou d'un fichier : version mineure ; renommage, suppression ou changement de type : version majeure et mise à jour simultanée du site |

## 2. Fichiers de `site/data/`

| Fichier | Schéma | Contenu | Unité | Millésime actuel | Producteur | État |
|---|---|---|---|---|---|---|
| `meta.json` | `meta.schema.json` | provenance, date de génération, totaux de contrôle | divers | généré à chaque passage | `transform.py` | existant |
| `arbre/racine.json` + `arbre/<chemin>.json` | `arbre_etat.schema.json` | arbre du budget de l'État (vue par défaut) | Md€ (CP) | Exécution 2024 | `transform.py` (budget vert PLF 2026 + PLRG 2024) | existant |
| `arbre_lfi2025/` | `arbre_etat.schema.json` | même arbre, crédits votés | Md€ (CP) | LFI 2025 | `transform.py` | existant |
| `arbre_plf2025_nature/` | `arbre_etat.schema.json` | vue séparée par nature (sous-action, titre, catégorie) | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `sankey_etat.json`, `sankey_etat_lfi2025.json` | `sankey_etat.schema.json` | flux État > grand poste > mission > programme | Md€ (CP) | Exécution 2024, LFI 2025 | `transform.py` | existant |
| `nature_etat.json` | `nature_etat.schema.json` | budget de l'État par titre et catégorie LOLF | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `programmes/<n>.json` | `programme.schema.json` | actions, sous-actions et nature d'un programme | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `arbre_administrations/racine.json` | `arbre_administrations.schema.json` | administration > fonction COFOG > sous-fonction | Md€ | 2024 | `transform.py` (Eurostat `gov_10a_exp`) | existant |
| `arbre_administrations/methode.json` | `arbre_administrations_methode.schema.json` | note de consolidation | Md€ | 2024 | idem | existant |
| `administrations.json` | `administrations.schema.json` | recettes, dépenses, solde par administration | Md€ | 2005 à 2025 | `transform.py` (Eurostat `gov_10a_main`) | existant |
| `recettes.json` | `recettes.schema.json` | chaque impôt par administration bénéficiaire | Md€ | 2005 à 2025 | `transform.py` (Eurostat `gov_10a_taxag`) | existant |
| `cofog.json` | `cofog.schema.json` | dépenses publiques consolidées par fonction | Md€ | 2024 | `transform.py` (Eurostat `gov_10a_exp`) | existant |
| `deficit.json` | `deficit.schema.json` | solde et part empruntée, État et APU | Md€ | État : LFI et exécution 2024-2025 ; APU 2015-2025 | `transform.py` | existant |
| `communes/<dep>.json` | `communes.schema.json` | taux TFB et TEOM par commune | % | Exercice 2025 | `transform.py` (DGFiP, REI) | existant |
| `nature/<programme>.json` | `nature_programme.schema.json` | nature réelle de la dépense | € | Exécution 2024 (PLRG) | `beneficiaires.py` | existant (126) |
| `effectifs/<programme>.json` | `effectifs.schema.json` | ETPT et coût moyen par ETPT | € | ETPT LFI 2023, titre 2 exécution 2024 | `beneficiaires.py` | existant (55) |
| `beneficiaires/programme_<n>.json` | `beneficiaires_programme.schema.json` | associations subventionnées, opérateurs | € | crédits 2023 (jaune PLF 2025), opérateurs PLF 2025 | `beneficiaires.py` | existant (110) |
| `beneficiaires/france2030.json` | `france2030.schema.json` | France 2030 par opérateur et bénéficiaire | € | projets décidés 2021 à 2025 | `beneficiaires.py` | existant |
| `beneficiaires/marches_etat.json` | `marches_etat.schema.json` | marchés publics des services de l'État | € HT | marchés notifiés en 2024 (DECP) | `beneficiaires.py` | existant |
| `beneficiaires/index.json` | `beneficiaires_index.schema.json` | index et totaux de contrôle | divers | | `beneficiaires.py` | existant |
| `realisations/<programme>.json` | `realisations.schema.json` | prévu/dépensé, indicateurs, réalisations, évaluations | € (CP) | exécution 2010-2025, performance 2012-2025 | `realisations.py` | existant (135) |
| `realisations/index.json` | `realisations_index.schema.json` | couverture, trous, fiabilité des règles | divers | | `realisations.py` | existant |
| `vie_politique/annees.json` | `vie_politique_annees.schema.json` | programme 232, aide aux partis, remboursements de campagne par année | € | exécutions 2018-2025, campagnes 2012-2024 | `vie_politique.py` | existant |
| `vie_politique/partis/<annee>.json` | `vie_politique_partis.schema.json` | aide publique par parti (1re et 2de fraction) | € | exercices 2008 à 2024 | `vie_politique.py` | existant |
| `vie_politique/scrutins/<scrutin>_<annee>.json` | `vie_politique_scrutin.schema.json` | agrégats d'un scrutin, par nuance si publiée | € | 2012 à 2024 | `vie_politique.py` | existant |
| `vie_politique/candidats/<scrutin>_<annee>.json` | `vie_politique_candidats.schema.json` | comptes de campagne par candidat | € | 2012 à 2024 | `vie_politique.py` | existant |
| `prelevements/affectation.json` | `prelevements_affectation.schema.json` | qui reçoit chaque prélèvement, une source par part | parts (0 à 1) | 2025 (PLFSS 2026, PLF 2026 Voies et moyens) | `prelevements.py` | existant |
| `prelevements/tva_conso.json` | `prelevements_tva_conso.schema.json` | TVA, TICPE, tabac, alcool par décile de niveau de vie | € par an et par UC | 2025 (Insee 2019 recalé sur Eurostat) | `prelevements.py` | existant |
| `prelevements/taxe_fonciere.json` | `prelevements_taxe_fonciere.schema.json` | méthode, limites, agrégats de l'estimation de taxe foncière | € | Exercice 2025 (REI) | `prelevements.py` | existant |
| `prelevements/taxe_fonciere/<dep>.json` | `prelevements_taxe_fonciere_dep.schema.json` | taxe foncière et TEOM estimées par commune, parts par bénéficiaire | € | Exercice 2025 (REI) | `prelevements.py` | existant |
| `affectation_prelevements.json` | `affectation_prelevements.schema.json` | ancien format prévu, remplacé à terme par `prelevements/affectation.json` | parts (0 à 1) | | | **prévu** |

Le millésime réel est toujours lu dans le fichier (`millesime`, `annee`, `annees`, clés d'année) ou dans `meta.json` (`millesime.etat_defaut`, `controle.exercice`, `controle.annee_cofog`, `controle.administrations_derniere_annee`, `controle.recettes_annees`, `controle.arbre_administrations.annee`) : le site ne code aucune année en dur.

### 2.1 `meta.json`

| Champ | Type | Sens |
|---|---|---|
| `millesime` | `{etat_defaut, etat_disponibles[], nature_etat}` | vue par défaut de l'arbre État et vues disponibles |
| `genere_le` | chaîne date-heure ISO 8601 | fin du passage du pipeline ; **ne déclenche jamais de commit à lui seul** (workflow `data.yml`) |
| `sources.<jeu>.source` | chaîne | identifiant de la source (portail/jeu) |
| `sources.<jeu>.maj_source` | chaîne ISO 8601 ou `null` | date de mise à jour déclarée par la source |
| `controle.etat.<vue>` | objet | une entrée par vue (`execution_2024`, `lfi_2025`, `nature_plf2025`) : `total_md`, `arbre` (`{noeuds, feuilles, profondeur, fichiers}`), `prelevements_sur_recettes_md`, `hors_perimetre_md`, `remboursements_et_degrevements` (montant exclu et motif), `rapprochement_plrg` |
| `controle.exercice` | `"AAAA"` | exercice des taux communaux |
| `controle.communes`, `controle.departements` | entiers | nombre de communes (≥ 30 000) et de départements (≥ 96) |
| `controle.annee_cofog`, `controle.administrations_derniere_annee`, `controle.tva_annee` | `"AAAA"` | millésimes Eurostat |
| `controle.recettes_annees` | `"AAAA-AAAA"` | plage de `recettes.json` |
| `controle.deficit_derniere_annee`, `controle.part_empruntee_apu_derniere_annee` | `["AAAA", nombre]` | dernier solde public, dernière part empruntée APU |
| `controle.part_empruntee_etat` | objet vue → part | part empruntée de l'État par vue budgétaire |
| `controle.tva_derniere_annee` | objet administration → Md€ | TVA par bénéficiaire |
| `controle.arbre_administrations` | `{noeuds, feuilles, profondeur, fichiers, annee, somme_md, ...}` | statistiques de l'arbre des administrations |
| `version_contrat` | `"1.3"` | **prévu** : à écrire par le pipeline ; le site refuse une version majeure différente |

### 2.2 Arbres (`arbre*/`, `arbre_administrations/racine.json`)

Un nœud : `{"id", "nom", "niveau", "md", "enfants"?, "fichier"?, "nb_enfants"?}`. La racine et chaque sous-arbre chargé à la demande portent aussi l'en-tête (`millesime`, `source`, `unite`, et pour la vue nature `libelle`, `avertissement`).

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | chemin des clés depuis la racine, séparées par `/` (ex. `Education et recherche/EC/141`) ; `racine` pour la racine |
| `nom` | chaîne | libellé affichable |
| `niveau` | énuméré | État : `racine`, `grand_poste`, `mission`, `programme`, `action`, `sous_action`, `titre`, `categorie` (ordre fixé par `pipeline/niveaux.json`) ; administrations : `racine`, `administration`, `fonction`, `sous_fonction` |
| `md` | nombre, 6 décimales | montant du nœud = somme de ses enfants. **Peut être négatif en exécution** (rétablissements de crédits, ex. programme 423 en 2024 : −0,077 Md€) ; ces programmes sont listés dans `programmes_negatifs_hors_sankey` du sankey. Toujours ≥ 0 dans l'arbre des administrations |
| `enfants` | tableau non vide de nœuds | triés par montant décroissant ; absent sur une feuille |
| `fichier` + `nb_enfants` | chaîne + entier | point de découpe (après `programme`) : sous-arbre à charger à la demande, dans le dossier de la vue (`arbre/`, `arbre_lfi2025/`, `arbre_plf2025_nature/`) ; exclusif de `enfants` |

Un niveau non renseigné par la source est sauté (branche moins profonde). Le validateur contrôle aussi que chaque `fichier` référencé existe. Dans l'arbre des administrations, la sous-fonction GF0108 (transferts entre administrations) est retirée ; la somme des administrations (1 732,7 Md€ en 2024) dépasse donc le total consolidé (1 671,8 Md€), expliqué par `methode.json`.

### 2.3 `sankey_etat.json` et `sankey_etat_lfi2025.json`

`{"millesime", "source", "unite", "total", "total_net_arbre", "nodes": [{"id", "name", "level"}], "links": [{"source", "target", "value"}], "programmes_negatifs_hors_sankey": [{programme, mission, md}]}`. `id` préfixé : `etat`, `p:<grand poste>`, `m:<mission>`, `g:<numéro de programme>`, `psr:<bénéficiaire>` (prélèvements sur recettes : collectivités, Union européenne) ; `level` 0 à 3 ; `source`/`target` = index dans `nodes` ; `value` en Md€ > 0. Conservation : à chaque niveau, la somme des liens sortants égale `total` ; `total_net_arbre` = `total` moins les programmes négatifs écartés du sankey.

### 2.4 `nature_etat.json` et `programmes/<n>.json`

`nature_etat.json` : `titres[]` de `{titre: "1".."7", nom, md, categories: [{code: "NN", nom, md}]}`.
`programmes/<n>.json` : `{programme: entier 100..999, unite, libelle, avertissement, actions: [{code, nom, md, sous_actions: [{code|null, nom|null, md}]}], nature: {libellé de catégorie: md}}`. `code`/`nom` de sous-action à `null` quand la source n'a pas de sous-action. Ces deux fichiers décrivent le PLF 2025 (vue séparée, aucun prorata appliqué à l'exécution) ; la nature réelle exécutée est dans `nature/<programme>.json` (2.9).

### 2.5 `administrations.json`

`annees.<AAAA>.<administration>.<agrégat>` = Md€. Agrégats : `TR` recettes, `TE` dépenses, `B9` solde, `D73PAY` transferts courants versés à d'autres administrations, `D92PAY` aides à l'investissement versées, `D99PAY` autres transferts en capital versés. Les quatre administrations sont présentes chaque année. Les clés `TR`, `TE`, `B9` de premier niveau donnent les libellés.

### 2.6 `recettes.json`

`{unite, annees: ["2005", ...], impots: {<code SEC>: {nom, par_administration: {<administration>: {<AAAA>: md}}}}}`. Codes présents : `D2`, `D211` (TVA), `D214A`, `D29`, `D5`, `D51A_C1` (impôt sur le revenu des ménages), `D51B`, `D61` (cotisations sociales), `D91`. `D211`, `D51A_C1` et `D61` sont obligatoires (utilisés par le calcul personnel). Une année absente pour une administration = pas de recette déclarée.

### 2.7 `cofog.json` et `deficit.json`

`cofog.json` : `{annee, unite, fonctions: [10 × {code: "GF01".."GF10", nom, md}], total}`.

`deficit.json` : deux comptabilités, jamais additionnées ni comparées directement (`avertissement`).

| Champ | Sens |
|---|---|
| `solde_public.<AAAA>` | solde public APU (Eurostat `gov_10dd_edpt1`), Md€, négatif = déficit |
| `etat.annees.<vue>` | comptabilité budgétaire de l'État par vue (`Exécution 2024`, `LFI 2025`...) : `recettes_nettes_bg_md`, `depenses_nettes_bg_md`, `fonds_de_concours_md`, `prelevements_sur_recettes_md`, `solde_comptes_speciaux_md`, `solde_budgets_annexes_md`, `solde_budgetaire_md`, `part_empruntee` ; formules dans `etat.formule_solde` et `etat.formule_part_empruntee` |
| `administrations_publiques.annees.<AAAA>` | comptabilité nationale S13 : `B9_md`, `TE_md`, `part_empruntee = -B9 / TE` |

### 2.8 `communes/<dep>.json`

Un fichier par département (`01` à `95`, `2A`, `2B`, `971` à `976`) : `{millesime, source, format, communes: {<code INSEE>: [nom, taux_tfb, taux_teom]}}`.

| Position | Type | Sens |
|---|---|---|
| 0 | chaîne | nom DGFiP (majuscules, sans accent) |
| 1 | nombre ou `null` | taux global de taxe foncière sur le bâti, en % (somme commune, EPCI et taxes annexes ; peut dépasser 100) |
| 2 | nombre ou `null` | taux plein de TEOM en % ; `null` = pas de TEOM (déchets financés par la REOM ou le budget général) |

Le département se déduit du code INSEE : 2 premiers caractères en métropole et Corse, 3 en outre-mer (`97411` → `974.json`).

### 2.9 Précision par programme : nature, effectifs, bénéficiaires (contrat 1.1)

Producteur : `pipeline/beneficiaires.py`. Montants en **euros**. Commandes : `python pipeline/beneficiaires.py resoudre associations france2030 acheteurs titulaires` (réseau, reprenable, `--budget` secondes), puis `python pipeline/beneficiaires.py tout` (sans réseau). Tests : `pytest tests/test_beneficiaires.py`.

```
data/lake (PLRG 2024, ETPT LFI 2023, jaune associations PLF 2025, jaune opérateurs PLF 2025, France 2030, DECP)
   + API Recherche d'entreprises (catégorie juridique, cache data/lake/_cache/)
        └─> pipeline/beneficiaires.py ─> site/data/nature/  site/data/effectifs/  site/data/beneficiaires/
```

**Règle personnes physiques (bloquante).** Seules les personnes morales sont nommées : catégorie juridique `2xxx` à `9xxx`, lue dans la source ou via l'API. Tout objet portant `siren` porte aussi `categorie_juridique` conforme (le schéma refuse `1000`, entrepreneur individuel, et toute clé contenant « prénom »). Le reste est agrégé dans `exclus_personnes_physiques_ou_non_identifies` (entrepreneurs individuels, SIREN absent ou invalide comme « NR CHORUS », catégorie introuvable) ou dans `autres_non_verifies` (SIREN valide pas encore vérifié). Le CSV `beneficiaires/beneficiaires_publies.csv` est validé par Frictionless (`datapackage.json`, motif `^[2-9][0-9]{3}$`).

**Groupe de bénéficiaires** (`commun.schema.json#/$defs/groupe_beneficiaires`). Conservation, contrôlée par le validateur : `somme(top.montant_eur) + autres_personnes_morales.montant_eur + autres_non_verifies.montant_eur + exclus_personnes_physiques_ou_non_identifies.montant_eur = total` (à 1 € près).

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
| `exclus_personnes_physiques_ou_non_identifies` | `{montant_eur, lignes, dont_..._eur}` | montant agrégé exclu ; `dont_personnes_physiques_eur` et selon la source `dont_siren_nr_chorus_eur`, `dont_sans_siren_eur`, `dont_identifiant_non_siret_eur`, `dont_categorie_inconnue_eur` |

**`nature/<programme>.json`** : nature réelle de la dépense 2024 (PLRG 2024, annexe 1 « titre × catégorie », dépenses constatées), un fichier par programme du PLRG (126).

| Champ | Type | Sens |
|---|---|---|
| `millesime` | `"Exécution 2024"` | |
| `programme`, `libelle`, `mission` | chaînes | `programme` sur 3 chiffres |
| `total_eur`, `eur_sur_100` | nombres | total du programme |
| `postes[]` | `{id, libelle, categories[], eur, part_programme_pct, eur_sur_100}` | regroupement lisible ; `id` parmi `salaires` (21), `cotisations` (22), `prestations_employeur` (23), `fonctionnement` (31), `subventions_operateurs` (32), `interventions_menages` (61), `interventions_entreprises` (62), `interventions_collectivites` (63), `interventions_autres` (64), `appels_garantie` (65), `investissement` (51 à 53), `dette` (41 à 43), `pouvoirs_publics` (10), `operations_financieres` (71 à 73) |
| `categories[]` | `{code, libelle, eur}` | catégories LOLF brutes |
| `controle_arbre` | `{millesime_arbre, total_arbre_eur, ecart_eur, ecart_pct, explication}` | écart avec le nœud programme de l'arbre ; montants `null` si le programme n'est pas dans l'arbre (200, 201) |

Contrôle : la somme des programmes présents dans l'arbre s'écarte de l'arbre de `controle.nature.ecart_global_pct` (1,93 %) ; tolérance publiée `controle.nature.tolerance_pct` = 3 % (`beneficiaires/index.json`). Les écarts par programme viennent des retraitements du budget vert (fonds de concours, périmètre 2026) : par exemple 203 (+94 %), 345 (+125 %), 135 (−53 %).

**`effectifs/<programme>.json`**

| Champ | Type | Sens |
|---|---|---|
| `etpt`, `millesime_etpt` | nombre ou `null`, `"LFI 2023"` | plafond d'emplois voté, dernier millésime publié par programme (`nature_etpt` le rappelle) |
| `categories_emploi[]` | `{categorie_emploi, etpt}` | |
| `titre2_eur`, `millesime_titre2` | nombre ou `null`, `"Exécution 2024"` | catégories 21 + 22 + 23 du PLRG 2024 |
| `eur_sur_100_titre2` | nombre ou `null` | |
| `cout_moyen_par_etpt_eur` | entier ou `null` | `titre2_eur / etpt` (coût complet employeur, pensions comprises) |
| `avertissement` | chaîne ou `null` | millésimes différents ; programme sans ETPT publié |

**`beneficiaires/programme_<n>.json`**

| Champ | Type | Sens |
|---|---|---|
| `programme`, `libelle`, `mission`, `dans_arbre` | | rattachement à l'arbre (`libelle`, `mission` à `null` hors arbre) |
| `programme_arbre_eur`, `programme_eur_sur_100` | nombres ou `null` | taille du programme dans l'arbre 2024 |
| `associations` | objet ou `null` | groupe de bénéficiaires + `millesime` (« Crédits versés en 2023 »), `source`, `total_source_eur`, `lignes_source`, `personnes_morales`, `eur_sur_100` ; `top[]` ajoute `objet` et `lignes` |
| `operateurs` | objet ou `null` | `{millesime: "PLF 2025", source, note, nombre, liste[{operateur, categorie, statut}]}`, opérateurs dont le programme est chef de file, sans montant (la source n'en donne pas) |

**`beneficiaires/france2030.json`** : `millesime` = projets décidés de 2021 à 2025 (montants engagés cumulés, subvention + avance remboursable). `lignes_source`, `doublons_exacts_retires`. `ensemble` et `par_operateur.<Bpifrance|ANR|ADEME|Caisse des Dépôts|DGAC|CNES>` : groupe de bénéficiaires + `total_eur`, `projets`, `beneficiaires_personnes_morales` ; `top[]` ajoute `typologie`, `operateurs[]`, `projets`. `par_programme.<424|425>` : `{total_eur, projets, libelle}` (rattachement par le code action de la source).

**`beneficiaires/marches_etat.json`** : `millesime` = marchés notifiés en 2024. Périmètre : acheteurs de catégorie juridique `71xx` (services de l'État). `ensemble` et `par_ministere.<ministère>` (dont « État, ministère non identifié ») : groupe de bénéficiaires + `total_eur`, `nombre_marches` ; `top[]` ajoute `nombre_marches`. `ecartes_montants_aberrants` : `{montant_eur, lignes}`. Rattachement au ministère d'après le nom SIRENE de l'acheteur (le programme n'existe pas dans les DECP).

**`beneficiaires/index.json`** : `programmes[]` (numéros), `fichiers` (chemins relatifs à `site/data/`), `regle_personnes_physiques`, `controle` (totaux et écarts de chaque étape, dont `controle.nature.tolerance_pct`).

**Tables Frictionless** (`datapackage.json`) : `beneficiaires/beneficiaires_publies.csv` (source, groupe, siren, denomination, categorie_juridique, montant_eur), `nature/nature_2024.csv` (programme, categorie, libelle_categorie, eur), `effectifs/effectifs.csv` (programme, etpt_lfi_2023, titre2_execution_2024_eur, cout_moyen_par_etpt_eur).

### 2.10 « Ce qui a été fait » : `realisations/` (contrat 1.2)

Producteur : `pipeline/realisations.py`. Montants en **euros** (CP). Chaque fichier porte `millesime`, `source` et `avertissement` (texte fixe : « Les indicateurs sont choisis par l'administration ; une évolution ne prouve pas l'effet de la dépense. »). Commandes : `python pipeline/realisations.py collecter` (réseau, reprenable, `--budget` secondes pour la vérification des liens ; écrit dans `data/lake/etat/realisations/` et `data/lake/_cache/ccomptes/`), puis `python pipeline/realisations.py produire` (sans réseau). Tests : `pytest tests/test_realisations.py`.

```
data/lake (PLRG 2023-2025 annexe 1 « état CP », RAP de synthèse 2019-2020, budget vert PLF 2024,
           exécution 2010-2014 et LFI 2011-2014, RAP/PAP 2015-2025 volet performance)
   + ccomptes.fr (pages « Le budget de l'État en <année> », flux RSS publications, vérification HTTP des liens)
   + site/data/beneficiaires/ (programme_<n>.json, france2030.json)
        └─> pipeline/realisations.py ─> site/data/realisations/<programme>.json  site/data/realisations/index.json
```

**`realisations/<programme>.json`** : un fichier par programme présent dans les annexes PLRG 2023 à 2025 (135). `programme` (3 chiffres), `libelle`, `mission` (libellés du dernier PLRG), `unite_montants`, puis quatre blocs.

1. `prevu_depense` : `annees[]` (ordre chronologique), `lecture`, `note_perimetre` ; `note` si le programme n'a aucune année.

| Champ | Type | Sens |
|---|---|---|
| `annee` | entier | exercice |
| `source` | chaîne ou `null` | jeu et pièce jointe d'origine ; `null` pour un trou |
| `vote_lfi_eur` | nombre ou `null` | crédits votés en loi de finances initiale (absent pour 2010, 2018, 2022) |
| `ouvert_en_gestion` | objet ou `null` | PLRG 2023-2025 seulement : `total_eur`, `lfr_eur`, `reports_entrants_eur`, `mouvements_reglementaires_eur`, `fonds_de_concours_et_attributions_de_produits_eur`, `fongibilite_asymetrique_eur` |
| `depense_constatee_eur` | nombre ou `null` | dépenses constatées |
| `ecart_eur`, `ecart_pct` | nombres ou `null` | `depense - vote` (arrondi au centime) et `(depense - vote) / vote × 100` (2 décimales) ; `null` si l'un manque |
| `ecart_ouvert_eur` | nombre | `depense - ouvert_en_gestion.total_eur` (PLRG) |
| `eur_sur_100` | nombre | 2024 seulement |
| `trou` | chaîne | année sans donnée publiée : 2015, 2016, 2017 (aucune exécution par programme en données ouvertes), 2021 (ni PLR ni RAP de synthèse) |

Sources par année : 2010-2014 exécution du budget général et LFI 2011-2014 ; 2018 consommation lue dans le RAP de synthèse 2019 ; 2019 et 2020 RAP de synthèse (feuille « Crédits ») ; 2022 budget vert PLF 2024 (`execution_2022_cp`) ; 2023-2025 PLRG, annexe 1 « état CP ».

2. `resultats_mesures` : `indicateurs[]` (une entrée par couple indicateur × sous-indicateur, les plus récents d'abord), `note` (si aucun indicateur), `lecture`.

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | `<programme>-<n>`, stable à données égales |
| `code_indicateur` | chaîne ou `null` | code externe `P141-1-2` (normalisé depuis `P141.1.2` et `141-1-2`) |
| `objectif`, `indicateur`, `sous_indicateur`, `unite` | chaînes | libellés de la source la plus récente |
| `libelles_anterieurs` | tableau ou `null` | autres libellés rapprochés de la même série |
| `indicateur_de_contexte` | booléen ou `null` | colonne `contexte` du RAP 2025 |
| `valeurs[]` | `{annee, valeur, brut, source}` | réalisé ; `valeur` nettoyée (virgule décimale, espaces, « (± x) ») ou `null` (« nd », « sans objet »...) ; `brut` = texte publié |
| `cibles[]` | `{annee, valeur, brut, source, note?}` | cible du PAP de l'année ; `note: "cible de moyen terme"` pour `valeur_cible` / `annee_cible` |
| `ecarts_a_la_cible[]` | `{annee, realise, cible, ecart, atteinte_publiee}` | `ecart = realise - cible` ; `atteinte_publiee` = texte de la source |
| `sens_souhaite` | `{valeur, methode, source, justification, comparaisons?}` | `valeur` : `hausse`, `baisse`, `stabilité` ou `inconnu` ; `methode` : `colonne evolution` (RAP 2025), `position des cibles`, ou `null` |
| `tendance` | objet | `valeur` : `en progrès`, `en recul`, `stable` (variation ≤ 1 % entre les deux dernières valeurs), `sens inconnu` ; `de_annee`, `a_annee`, `de`, `a`, `variation`, `variation_relative_pct` ; `justification` ou `raison` |
| `rapprochement` | objet | nombre de lignes source rattachées par `code`, `libellé`, `création` |

Rapprochement des séries : sources lues de la plus récente à la plus ancienne (RAP 2025 ... PAP 2015) ; une valeur d'une année vient de la source la plus récente qui la publie. Une ligne rejoint une série par code externe si le libellé d'indicateur partage au moins la moitié de ses mots, puis par libellé exact. `facteur_de_performance` ne donne pas de sens et n'est pas utilisé.

3. `realisations_concretes` : `liste[]` (≤ 10, montant décroissant, `{objet, beneficiaire, siren, montant_eur, eur_sur_100, type}`, repris de `beneficiaires/programme_<n>.json`), `fichier_beneficiaires` (chemin ou `null`), `france2030` (programmes 424 et 425 : `{total_eur, projets, millesime, source, fichier, note}`, sinon `null`), `millesime`, `source`, `note`.

4. `evaluations` : `liens[]` (`type` « note d'exécution budgétaire (NEB) » ou « publication », `annee_execution`, `titre`, `titre_publie`, `url`, `page`, `rattachement`, `verifie: true`, `verifie_le`, `statut_http: 200`), `liens_ecartes_non_verifies` (entier), `note` (raison d'un champ vide, ex. mission « Pouvoirs publics », sans NEB). Un lien n'est publié qu'après un appel HTTP 200 (et contenu PDF pour les NEB) ; rattachement par titre exact de mission ou de programme.

**`realisations/index.json`** : `programmes[]`, `fichiers`, `couverture` (programmes ayant chaque bloc), `trous_execution`, `annees_execution`, `annees_performance`, `sources_performance`, `rapprochement_indicateurs`, `tendances` (comptes par valeur), `fiabilite_regle_position_cibles` (78 % de concordance avec la colonne `evolution`), `reculs_les_plus_marques` et `reculs_criteres`, `evaluations`.

### 2.11 Argent public et vie politique : `vie_politique/` (contrat 1.3)

Producteur : `pipeline/vie_politique.py`. Montants en **euros**. Collecte (réseau, reprenable) : `python pipeline/vie_politique.py collecte {cnccfp|presidentielles|budget|tout}` ; production (sans réseau) : `python pipeline/vie_politique.py produire`. Tests : `pytest tests/test_vie_politique.py`. Entrées : `data/lake/_restreint/politique/` (tout ce qui nomme un candidat) et `data/lake/politique/` (partis, programme 232).

| Fichier | Contenu |
|---|---|
| `annees.json` | `annees[]` de `{annee, programme_232 (ou null + programme_232_manquant), aide_publique_partis (ou null), remboursements_campagne[], remboursements_campagne_total_eur}` ; `programme_232.actions_eur` = `financement_des_partis`, `organisation_des_elections`, `cnccfp` (actions 01 à 03 ; cultes et vie associative exclus et signalés dans `hors_perimetre_eur`), `euros_sur_100_euros_etat`. `scrutins[]` (`{scrutin, annee, libelle, fichier, nombre_candidats, depenses_totales_eur, remboursement_etat_total_eur}`), `trous[]`, `controle_remboursements_vs_organisation_des_elections[]`, `perimetre`, `collecte_le` |
| `partis/<annee>.json` | `exercice` (entier), `partis[]` de `{code_cnccfp, nom, premiere_fraction_eur, seconde_fraction_eur, total_eur}`, totaux, `definition`, `avertissements[]` (partis sans ventilation par fraction) |
| `scrutins/<scrutin>_<annee>.json` | agrégats seulement, **aucun candidat nommé** (le schéma interdit `candidat`/`candidats`) : `nombre_candidats`, `depenses_totales_eur`, `recettes_totales_eur`, `remboursement_etat_total_eur`, `apport_personnel_total_eur`, `dons_totaux_eur`, `decisions.<code CNCCFP>` (`{libelle, nombre}`, codes de la source gardés tels quels), comptes rejetés, hors délai, non déposés, `par_nuance[]` quand la source donne la nuance, `definitions`, `avertissements[]` |
| `candidats/<scrutin>_<annee>.json` | exception personnes physiques : `regle`, `champs[]` et `candidats[]`. **Liste blanche** (`CHAMPS_CANDIDAT` du producteur, `additionalProperties: false` au schéma) : `candidat`, `nuance`, `parti`, `circonscription`, `tour`, `elu`, `depenses_eur`, `recettes_eur`, `apport_personnel_eur`, `dons_eur`, `remboursement_eur`, `decision`, `reference`. Ni adresse, ni date de naissance, ni donateur, ni mandataire financier. Publié seulement si `AFFICHER_CANDIDATS` ; le détail complet reste dans `data/processed/_restreint/` (jamais versionné) |

`scrutin` ∈ `legislatives`, `presidentielle`, `europeennes`, `municipales`, `departementales`, `regionales`, `senatoriales`, `partielles`, `territoriales_corse`, `territoriales_saint_martin_saint_barthelemy`. Liens `fichier` de `annees.json` relatifs à `vie_politique/` (écart à la règle commune, voir 1).

### 2.12 Prélèvements hors bulletin et affectation : `prelevements/` (contrat 1.4)

Producteur : `pipeline/prelevements.py`. Chaque fichier porte `millesime` et `source` ; les trois fichiers de tête portent aussi `methode`. Commandes : `python pipeline/prelevements.py collecter` (réseau, reprenable, ne retélécharge pas un fichier présent, s'arrête sur un refus d'accès sans le contourner), `python pipeline/prelevements.py produire` (sans réseau), ou sans argument pour les deux. Tests : `pytest tests/test_prelevements.py`.

```
data/lake/prelevements/ (Insee IA 88, Budget de famille 2017 TF106 et TF306, PLFSS 2026 annexe 3, PLF 2026 Voies et moyens tome I)
+ data/lake/fiscalite/... REI 2025 (DGFiP)   + data/lake/comptes_nationaux/insee_ds_erfs_non_retropole.zip
+ site/data/recettes.json (Eurostat gov_10a_taxag)
     └─> pipeline/prelevements.py ─> site/data/prelevements/affectation.json, tva_conso.json, taxe_fonciere.json,
                                     taxe_fonciere/<dep>.json
```

Les paramètres lus dans les PDF officiels sont saisis dans le module avec leur page, puis vérifiés à chaque `produire` contre le texte extrait du PDF (`verification_documents`) : si le document change, la production échoue au lieu de publier un chiffre périmé.

**`prelevements/affectation.json`** (remplace à terme `affectation_prelevements.json`, 2.13 ; destinataires hors de l'énumération 3.5 : ACOSS, MSA, AFITF, collectivités territoriales, audiovisuel public...).

| Champ | Type | Sens |
|---|---|---|
| `annee`, `millesime` | `"2025"` | année des parts |
| `source`, `methode` | chaînes | |
| `verification_documents` | objet | par document : `statut` (`vérifié` ou document absent), `motifs`, `manquants` |
| `destinataires.<id>` | `{nom, administration}` | `administration` parmi `Etat`, `Collectivites locales`, `Securite sociale` |
| `prelevements.<id>` | objet | `libelle`, `statut` (`sourcee` ou `non sourcee`), `ventilation[]` de `{destinataire, part, source, montant_md?, points?, dont?, note?}`, `reference_juridique`, `note` |
| `correspondance_calcul` | objet | `id` de prélèvement du module de calcul (3.3) → `id` de ce fichier |
| `sources`, `sources_ecartees` | objet, tableau | URL ou page, licence, verdict de réutilisation, raison de l'écart |

Pour `statut = sourcee`, la somme des `part` vaut 1 à 10⁻⁴ près et chaque `destinataire` existe dans `destinataires` (contrôlé par le validateur). Une part introuvable n'est jamais estimée : le prélèvement passe en `non sourcee` ou la `note` dit quel niveau de détail manque. Prélèvements 2025 : `vieillesse_plafonnee`, `vieillesse_deplafonnee`, `maladie`, `famille`, `atmp`, `agirc_arrco`, `ceg`, `chomage`, `fnal`, `csa`, `csg_activite`, `crds`, `impot_revenu`, `tva`, `ticpe`, `tabac`, `alcool`, `taxe_fonciere`, `teom`. Usage par le site : pour un prélèvement du résultat de calcul d'`id` X, lire `correspondance_calcul[X]`, puis répartir `montant_annuel_eur` selon `ventilation` (remplace le destinataire `plusieurs` de la CSG).

**`prelevements/tva_conso.json`**

| Champ | Type | Sens |
|---|---|---|
| `unite` | chaîne | euros par an et par unité de consommation (UC) ; montant du ménage = valeur × nombre d'UC |
| `deciles_niveau_de_vie` | `{annee, bornes_eur_par_an[9], source}` | bornes ERFS pour placer le ménage (niveau de vie = revenu disponible / UC) |
| `recalage` | objet | facteur 2019 → 2025 (Eurostat D2 - D29), part attribuée aux ménages par l'Insee, lecture de l'écart |
| `totaux_nationaux_2025_md.<taxe>` | `{md, source}` | `tva`, `ticpe`, `tabac`, `alcool`, `autres` |
| `ecarts_au_total_national.<taxe>` | `{estime_md, reel_md, ecart_pct}` | somme des déciles × UC comparée au total national réel |
| `tranches[10]` | objet | `decile` (1 à 10), `niveau_de_vie_min_eur` / `niveau_de_vie_max_eur` (`null` aux extrémités), `taxes_produits_eur_par_uc` `{bas, central, haut}`, `taux_effort_pct_revenu_disponible_2019`, `detail_eur_par_uc.<taxe>` `{bas, central, haut, part}`, `ajustements.voiture` (`taux_equipement_pct_2017`, `ticpe_si_voiture_eur_par_uc`, `ticpe_sans_voiture_eur_par_uc`), `ajustements.fumeur` (`tabac_non_fumeur_eur_par_uc` = 0, `tabac_fumeur_eur_par_uc` = `null` car non sourcé, `note`) |
| `non_sourcé` | tableau | ce qui n'est pas publié faute de source |

Lecture : `central` = hypothèse Insee de référence (taxes réparties comme la consommation) ; `bas`/`haut` = encadrement par la variante Insee où ces taxes pèsent sur les revenus. Ajustement voiture : remplacer `detail.ticpe.central` par `ticpe_si_voiture...` ou 0. Ajustement non-fumeur : retirer `detail.tabac`.

**`prelevements/taxe_fonciere.json`** : `methode[]`, `limites[]`, `agregats_nationaux_m` (millions d'euros 2025 par destinataire), `couverture`, `departements[]`, `fichiers`.

**`prelevements/taxe_fonciere/<dep>.json`** : mêmes départements que `communes/<dep>.json`, objet `communes` `{<code INSEE>: tableau ou null}` ; `null` pour toute la commune quand la base ou le montant est nul au REI.

| Position | Sens |
|---|---|
| 0, 1, 2 | taxe foncière d'un logement, propriétaire : bas, central, haut (euros par an) |
| 3, 4, 5 | TEOM refacturée au locataire : bas, central, haut ; `null` = pas de TEOM |
| 6 à 11 | parts de la cotisation de la commune : commune, EPCI (y compris GEMAPI), syndicats, taxes spéciales d'équipement, Région Île-de-France (TASA), frais de gestion de l'État ; somme = 1 (contrôlée) |

Si l'utilisateur saisit son avis (`logement.taxe_fonciere_annuelle_eur`), ce montant remplace l'estimation et seules les parts 6 à 11 servent.

### 2.13 `affectation_prelevements.json` (prévu, remplacé à terme)

`{annee, source, destinataires: {<id>: {nom, administration, url?}}, prelevements: {<id prélèvement>: {libelle?, ventilation: [{destinataire, part}], reference_juridique?}}}`. La somme des `part` d'un prélèvement vaut 1. Format remplacé à terme par `prelevements/affectation.json` (2.12) ; tant que le site ne lit ni l'un ni l'autre, les prélèvements partagés (CSG) ont le destinataire `plusieurs` et un avertissement `DONNEE_ABSENTE`.

### 2.14 Traçabilité et décisions : `tracabilite/` et `decisions/`

Producteurs : `pipeline/tracabilite.py` (sans réseau, lit `arbre/`, `nature/`, `beneficiaires/`, `vie_politique/` et le PLRG 2023) et `pipeline/decisions.py` (`jorf` : archive JORF de la DILA lue en flux, cache `data/lake/_cache/decisions_jorf/` ; `produire` : sans réseau). Montants en euros. Schémas : `tracabilite_noeud`, `tracabilite_resume`, `decisions_programme`, `decisions_amendements_resume`, `decisions_scrutins`, `decisions_mouvements`, `decisions_coherence_plrg`, `decisions_index`.

**Traçabilité (exécution 2024).** `tracabilite/programme_<n>.json` (un par programme de l'arbre) et `tracabilite/noeud_psr_<x>.json` (prélèvements sur recettes) ; `tracabilite/resume.json` : `global`, `grands_postes[]`, `missions[]`, `programmes[]`. Chaque nœud est partagé en quatre `parts` dont les `pct` somment à 100 :

| Part | Sens |
|---|---|
| `beneficiaire_identifie` | bénéficiaire nommé par une source publique (associations, marchés de l'État, France 2030, partis et remboursements de campagne, bénéficiaire unique désigné par le programme, Union européenne) ou catégorie fixée par la loi (collectivités : prélèvements, dotations 119 et 122) ; `niveau_identification` = `entite` ou `categorie` |
| `nominatif_par_choix` | titre 2 : la catégorie d'agents est publiée, pas les noms |
| `anonyme_par_nature` | charge et amortissement de la dette (catégories 41 à 43, programme 369) |
| `non_publie` | le reste ; un programme net négatif y est rangé en entier |

Une part porte `{libelle, eur, pct, statut, ecart_millesime_ans, sources[]}` ; `statut` = `exact` (numérateur et dénominateur de la même année) ou `approche` (avec l'écart de millésime et `raison_approche` dans `composantes`) ; une part non nulle a au moins une source. `maillons[]` donne des couvertures indépendantes : `programme` (100), `nature`, `destinataire` (= `taux_tracabilite_pct`), `beneficiaire_nomme`.

**Décisions.** `decisions/programme_<n>.json` : `annees.<AAAA>` (LFI, LFR, reports, mouvements réglementaires, fonds de concours, ouverts et dépenses du PLRG 2023 à 2025 ; comptes d'amendements ; `amendements_adoptes[]` ; `mouvements_jo[]`) et `chronologie[]` triée. `amendements_resume.json` : amendements de crédits déposés et adoptés (séance, commission) et montant net par programme et par année, Assemblée et Sénat, 17e législature. `scrutins.json` : scrutins publics de l'Assemblée sur les lois de finances (ensemble, parties, articles, crédits, amendements de crédits). `mouvements_<AAAA>.json` (2021 à 2026) : décrets et arrêtés de mouvements de crédits (avance, annulation, virement, transfert, répartition, report, fonds de concours) avec leurs lignes par programme, montants signés (ouverture > 0). `coherence_plrg.json` : somme des lignes JO par colonne du PLRG (mouvements réglementaires, reports, fonds de concours), écart publié et `conforme` d'après la tolérance publiée (1 % par an, 1 000 € par programme). `index.json` : programmes, fichiers, comptes, limites.

Auteurs : `{type, nom, groupe}` ; seuls les élus, le Gouvernement et les commissions sont nommés. Un élu qui a été candidat national (présidentielle, tête de liste européenne) est publié sans nom, avec `masque` (règle de 2.11).

### 2.15 « Près de chez moi » : `local/` (pipeline/local.py)

Pour une commune : ce que dépensent la commune, son intercommunalité, son département et sa région, les dotations de l'État, les taux d'impôts locaux et, là où c'est publié, les subventions votées. Montants en **euros** ; `eur_hab` = `eur` / population de l'exercice (2 décimales). Détail des champs et méthode : `docs_a_integrer/schemas_local.md`.

| Fichier | Schéma | Contenu | Source |
|---|---|---|---|
| `local/index.json` | `local_index` | blocs disponibles par commune (masque de bits sur `blocs`), SIREN des départements et régions | pipeline |
| `local/geo/<dep>.json` | `local_geo` | commune → population, EPCI, département, région | geo.api.gouv.fr |
| `local/budgets/communes/<dep>.json`, `departements.json`, `regions.json` | `local_budget` | 21 grands agrégats, 4 derniers exercices | OFGL comptes consolidés |
| `local/budgets/epci/<dep siège>.json` | `local_budget_epci` | EPCI + bloc communal consolidé (`ofgl-base-ei`, flux croisés retirés) | OFGL |
| `local/budgets/fonctions/departements.json`, `<siren>.json` | `local_fonctions_departements`, `local_fonctions` | dépenses par fonction (départements ; pilote 44 et Bretagne) | OFGL, Mégalis, Nantes Métropole |
| `local/dotations/communes/<dep>.json`, `epci.json`, `departements.json`, `regions.json` | `local_dotations_*` | DGF et composantes, DCRTP, DILICO ; DETR/DSIL/DPV/DSID par projet | DGCL via OFGL, data.gouv |
| `local/taux/<dep>.json` | `local_taux` | taux votés par niveau (TFB, TFNB, THRS, TEOM), 3 exercices | DGFiP REI |
| `local/decisions/index.json`, `<siren>/index.json`, `<siren>/<annee>.json` | `local_decisions_*` | subventions votées par collectivité, couverture publiée | SCDL, Région Pays de la Loire, SIRENE |

Règles propres à ce bloc : on n'additionne jamais commune + EPCI (le bloc communal consolidé de l'OFGL sert à cela) ni département ou région au bloc communal. Bénéficiaires nommés : personnes morales seulement (`sirene.personne_morale`, groupements de personnes physiques exclus) ; le reste est agrégé dans `exclus_personnes_physiques_ou_non_identifies`. Les textes libres (objets de subvention, intitulés de projets, objets de délibération) sont remplacés par `null` s'ils contiennent une civilité ou un prénom suivi d'un nom.

## 3. Module de calcul personnel

Exécuté dans le navigateur avec `modele-social` et `publicodes` (MIT). Entrée : un **profil** (`profil.schema.json`). Sortie : un **résultat** (`resultat.schema.json`, succès ou erreur). Exemples validés : `docs/exemples/`.

### 3.1 Entrée : profil

```json
{
 "version_contrat": "1.0",
 "annee_revenus": 2025,
 "residence": {"zone": "metropole", "alsace_moselle": false, "commune_insee": "69123"},
 "foyer": {"situation": "celibataire", "enfants": []},
 "logement": {"statut": "locataire"},
 "personnes": [{"role": "declarant1", "annee_naissance": 1985, "statut_activite": "salarie_prive",
   "frontalier": false, "cadre": false, "temps_travail": {"type": "temps_plein"},
   "salaire_net_avant_impot_mensuel": 2100}]
}
```

| Champ | Type | Règle |
|---|---|---|
| `residence.zone` | `metropole` / `dom` / `etranger` | V1 : `metropole` |
| `residence.alsace_moselle` | booléen | V1 : `false` (régime local : cotisation maladie supplémentaire) |
| `residence.commune_insee` | 5 caractères, facultatif | sert à la taxe foncière et à la TEOM |
| `foyer.situation` | `celibataire` / `parent_isole` / `couple_marie_pacse` / `couple_union_libre` | couple : 2 personnes ; sinon 1. Union libre : deux foyers fiscaux, enfants rattachés au déclarant 1 |
| `foyer.enfants[]` | `{annee_naissance, garde_alternee}` | enfants à charge (0 à 10) |
| `logement.statut` | `locataire` / `proprietaire` / `loge_gratuitement` | |
| `logement.taxe_fonciere_annuelle_eur` | nombre ou `null` | montant lu sur l'avis ; sans lui, seul le taux communal est montré |
| `personnes[].statut_activite` | énuméré (voir 3.2) | V1 : au moins un `salarie_prive`, l'autre `salarie_prive` ou `sans_activite` |
| `personnes[].cadre` | booléen | requis si salarié (retraite complémentaire, APEC) |
| `personnes[].temps_travail` | `{type: temps_plein}` ou `{type: temps_partiel, quotite: 0..1}` | |
| `personnes[].salaire_net_avant_impot_mensuel` | nombre > 0, euros | voir aide à la saisie |

**Aide à la saisie du salaire** (texte affiché à côté du champ) : « Prends sur ta fiche de paie la ligne **Net à payer avant impôt sur le revenu**. Si tu touches des primes ou un 13e mois, fais la moyenne sur 12 mois : additionne le net avant impôt de tes 12 dernières fiches et divise par 12. N'utilise ni le *net imposable*, ni le *montant net social*, ni le *net payé* (après prélèvement à la source). »

### 3.2 Périmètre V1 et sorties hors V1

V1 = salariés du secteur privé, résidant et travaillant en France métropolitaine, hors Alsace-Moselle. Les contrôles s'appliquent dans cet ordre ; le premier qui échoue produit `PROFIL_HORS_V1` avec son `motif` :

| Ordre | Condition | `motif` | Message (résumé) |
|---|---|---|---|
| 1 | `zone = dom` | `dom` | taux et abattements spécifiques aux DOM pas encore couverts |
| 2 | `zone = etranger` | `etranger` | non-résidents imposés différemment |
| 3 | `alsace_moselle = true` | `alsace_moselle` | régime local d'assurance maladie pas encore couvert |
| 4 | une personne `frontalier = true` | `frontalier` | cotisations payées dans le pays d'emploi |
| 5 | une personne `fonctionnaire` | `fonctionnaire` | pension civile, RAFP |
| 6 | `contractuel_public` | `contractuel_public` | Ircantec |
| 7 | `independant` | `independant` | cotisations TNS ou micro-entreprise |
| 8 | `retraite` | `retraite` | CSG et Casa sur pensions |
| 9 | `demandeur_emploi` | `demandeur_emploi` | allocations chômage |
| 10 | `apprenti` | `apprenti` | exonérations propres aux apprentis |
| 11 | `etudiant` sans salaire | `etudiant` | pas de salaire à analyser |
| 12 | aucune personne `salarie_prive` | `sans_activite_seul` | pas de salaire à analyser |

Chaque message propose une `redirection` vers l'exploration du budget sans calcul personnel. Un conjoint `sans_activite` reste dans le périmètre (couple à un revenu).

### 3.3 Sortie : résultat

```json
{"statut": "ok", "version_contrat": "1.0", "annee_legislation": 2025,
 "moteur": {"nom": "modele-social", "version": "...", "publicodes": "..."},
 "entree": {"personnes": [{"role": "declarant1", "salaire_net_avant_impot_annuel": 25200,
             "salaire_brut_annuel_estime": {"bas": 31834.39, "central": 31834.39, "haut": 31834.39}}]},
 "prelevements": [ ... ], "totaux": { ... }, "recoupement": { ... }, "avertissements": [ ... ]}
```

Chaque élément de `prelevements` :

| Champ | Type | Sens |
|---|---|---|
| `id` | `[a-z0-9_]+` | identifiant stable (`csg_deductible`, `vieillesse_plafonnee_salarie`, `impot_revenu`, ...) |
| `libelle` | chaîne | libellé affiché |
| `famille` | `cotisation_salariale` / `csg_crds` / `impot_revenu` / `cotisation_patronale` / `impot_local` | regroupement à l'écran |
| `personne` | `declarant1` / `declarant2` / `foyer` / `logement` | qui le paie |
| `assiette_annuelle_eur`, `taux` | nombre ou `null` | `taux` décimal (0,068 = 6,8 %), `null` pour un barème progressif |
| `montant_annuel_eur` | `{bas, central, haut}`, euros ≥ 0, bas ≤ central ≤ haut | voir 3.4 |
| `nature` | `prelevement` (défaut) / `reduction` | une réduction (réduction générale) est un montant positif à soustraire |
| `destinataire` | `{id, nom, administration}` | voir 3.5 |
| `ventilation` | `[{destinataire, part}]`, facultatif | prélèvement partagé, somme des parts = 1 |
| `inclus_dans_total_paye` | booléen | **`false` pour toutes les cotisations patronales** : bloc séparé, non additionné par défaut |
| `regle` | chaîne | règle `modele-social` (ex. `salarie . cotisations . CSG-CRDS`) à l'origine du chiffre |
| `hypothese_fourchette` | chaîne | ce qui fait varier bas et haut |

`totaux` : `paye_par_le_foyer` (somme des prélèvements `inclus_dans_total_paye`), `patronal` (bloc séparé, réductions déduites), `cout_total_employeur` (brut + patronal), `par_destinataire[]` (`{destinataire, montant_annuel_eur, inclut_patronal}` ; par défaut `inclut_patronal = false`, le site peut demander la variante qui l'inclut). Les fourchettes de totaux s'additionnent borne à borne (une réduction prend sa borne haute dans le total bas).

### 3.4 Fourchettes basse / centrale / haute

`central` = calcul `modele-social` avec ses valeurs par défaut. `bas` et `haut` encadrent ce que le profil ne dit pas :

| Paramètre inconnu | Effet | Borne basse | Borne haute |
|---|---|---|---|
| taux AT-MP de l'entreprise | patronal | 0,45 % | 4 % |
| versement mobilité (commune de l'employeur, effectif) | patronal | 0 | 3,2 % (Paris) |
| effectif de l'entreprise | FNAL, formation, apprentissage | moins de 11 salariés | 50 salariés et plus |
| droit à la réduction générale | patronal | réduction appliquée | réduction nulle |
| autres revenus du foyer, frais réels, réductions d'impôt | impôt sur le revenu | non pris en compte : bas = central = haut, signalé dans le texte |

Les cotisations salariales, la CSG et la CRDS sont déterministes à partir du brut (bas = central = haut), sauf si le brut lui-même est une fourchette.

### 3.5 Destinataires

| `id` | Nom | `administration` |
|---|---|---|
| `cnam` | Assurance maladie | Securite sociale |
| `cnav` | Assurance retraite (branche vieillesse) | Securite sociale |
| `cnaf` | Allocations familiales | Securite sociale |
| `branche_atmp` | Accidents du travail et maladies professionnelles | Securite sociale |
| `cnsa` | Branche autonomie | Securite sociale |
| `cades` | Caisse d'amortissement de la dette sociale (CRDS) | Securite sociale |
| `agirc_arrco` | Retraite complémentaire | Securite sociale |
| `unedic` | Assurance chômage | Securite sociale |
| `ags` | Garantie des salaires | Securite sociale |
| `apec` | Association pour l'emploi des cadres | Securite sociale |
| `fnal` | Fonds national d'aide au logement | Etat (à confirmer par `affectation_prelevements.json`) |
| `france_competences` | Formation professionnelle et apprentissage | Etat (à confirmer) |
| `aom` | Autorité organisatrice de la mobilité (versement mobilité) | Collectivites locales |
| `etat` | État (impôt sur le revenu) | Etat |
| `commune`, `epci`, `departement` | Collectivités (taxe foncière, TEOM) | Collectivites locales |
| `plusieurs` | Prélèvement partagé (CSG) en attente de ventilation | Securite sociale |

Agirc-Arrco, Unédic et CADES sont des administrations de sécurité sociale en comptabilité nationale : leur rattachement à `Securite sociale` rend les montants comparables avec `recettes.json` et `administrations.json`.

### 3.6 Recoupement OpenFisca

Sur action explicite de l'utilisateur (le profil, sans identifiant, est alors envoyé à `api.fr.openfisca.org`, ce qui est dit à l'écran), le site construit la même situation que `tests/cas_types/generer_reference.py`, appelle `POST /calculate` et compare cotisations salariales, CSG, CRDS, cotisations patronales nettes et impôt du foyer. Écart relatif > 1 % : `recoupement.statut = divergent` et avertissement `RECOUPEMENT_DIVERGENT` (non bloquant, les deux chiffres sont montrés). API injoignable : `indisponible` et avertissement `RECOUPEMENT_INDISPONIBLE`. Correspondance des variables :

| Contrat | OpenFisca (somme des 12 mois, signe inversé) |
|---|---|
| brut | `salaire_de_base` |
| net avant impôt | `salaire_net_a_payer` |
| cotisations salariales | `cotisations_salariales` |
| CSG | `csg_deductible_salaire` + `csg_imposable_salaire` |
| CRDS | `crds_salaire` |
| patronal (avant réduction) | `cotisations_employeur` |
| réduction générale | `allegement_general` (positif) |
| impôt sur le revenu | `impot_revenu_restant_a_payer` (foyer, année) |

## 4. États d'erreur

Une **erreur** (`statut: "erreur"`) remplace le résultat ; un **avertissement** accompagne un résultat valide.

| Code | Type | Déclencheur | Comportement du site |
|---|---|---|---|
| `PROFIL_HORS_V1` | erreur | profil hors périmètre (3.2), `motif` obligatoire | message explicite + redirection vers le budget, aucun chiffre personnel |
| `SAISIE_INVALIDE` | erreur | profil non conforme au schéma (net ≤ 0, quotité hors ]0 ; 1], couple à une personne...) ; `champ` = pointeur JSON | champ surligné, message court |
| `COMMUNE_INCONNUE` | erreur de la recherche de commune, avertissement dans un résultat | code INSEE absent de `communes/<dep>.json` | le calcul salarial continue sans taxe foncière ni TEOM ; proposer la recherche par nom |
| `DONNEE_ABSENTE` | erreur ou avertissement | fichier `site/data` introuvable (404) ou illisible, champ attendu `null`, fichier prévu pas encore produit ; `fichier` renseigné | bloc concerné masqué avec « donnée non disponible », le reste s'affiche |
| `TEOM_ABSENTE` | avertissement | taux TEOM `null` | « pas de TEOM dans ta commune (redevance ou budget général) » |
| `SAISIE_ATYPIQUE` | avertissement | net en équivalent temps plein inférieur au SMIC net, ou brut estimé > 4 plafonds annuels de la Sécurité sociale | résultat affiché, fiabilité signalée |
| `MOTEUR_INDISPONIBLE` | erreur | `modele-social` ou `publicodes` non chargé, règle introuvable | « calcul indisponible », exploration du budget toujours possible |
| `CONTRAT_INCOMPATIBLE` | erreur | `meta.version_contrat` de version majeure différente de celle du site | données non utilisées, message de maintenance |
| `RECOUPEMENT_DIVERGENT`, `RECOUPEMENT_INDISPONIBLE` | avertissement | voir 3.6 | non bloquant |

## 5. Cas types de référence

`tests/cas_types/cas_types.json` contient 20 profils conformes à `profil.schema.json` et, pour chacun, les valeurs annuelles 2025 calculées par l'API OpenFisca (`generer_reference.py`, tolérance 1 %, date et version d'`openfisca-france` enregistrées). Le module de calcul doit retrouver ces valeurs à 1 % près sur les agrégats du tableau 3.6 (avec les hypothèses `hypotheses_openfisca` du fichier : effectif 50, pas de versement mobilité, taux AT-MP par défaut d'OpenFisca). `pytest tests/cas_types` vérifie leur cohérence interne sans réseau.
