# Contrat d'interface pipeline / site

Version du contrat : **1.5** (17/11/2026).

| Version | Date | Changement |
|---|---|---|
| 1.0 | 15/11/2026 | fichiers budget de l'État, Eurostat, communes ; module de calcul personnel |
| 1.1 | 15/11/2026 | précision par programme : `nature/`, `effectifs/`, `beneficiaires/` |
| 1.2 | 16/11/2026 | bloc « Ce qui a été fait » : `realisations/` |
| 1.3 | 17/11/2026 | `vie_politique/` ; schémas 1.0 alignés sur les fichiers réellement produits (en-tête `millesime`/`source`, enveloppe `communes`, `deficit.json` État et APU, nœuds `psr:` du sankey, montants d'exécution négatifs, arbres LFI 2025 et nature PLF 2025) |
| 1.4 | 17/11/2026 | `prelevements/` : affectation sourcée de chaque prélèvement, taxes sur la consommation par décile, taxe foncière estimée par commune |
| 1.5 | 17/11/2026 | `secu/` : arbres Sécurité sociale et protection sociale (comptes des organismes, exécution 2024 et 2025 ; prestations DREES 2024), source, millésime et taux de traçabilité par nœud, écarts entre sources |

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
| `secu/arbre/racine.json` | `secu_arbre.schema.json` | dépenses des organismes de sécurité sociale et des régimes sociaux par branche et par nature (vue par défaut) | Md€ | Exécution 2024 | `secu.py` | existant |
| `secu/arbre_2025/racine.json` | `secu_arbre.schema.json` | même arbre, premier niveau publié | Md€ | Exécution 2025 | `secu.py` | existant |
| `secu/cps/racine.json` + `secu/cps/<chemin>.json` | `secu_arbre.schema.json` | prestations de protection sociale par secteur, régime, risque et prestation (DREES) | Md€ | 2024 | `secu.py` | existant |
| `secu/index.json` | `secu_index.schema.json` | vues, totaux, traçabilité, vérification des documents, sources, recherche préalable | divers | | `secu.py` | existant |
| `prestations/index.json` | `prestations_index.schema.json` | prestations versées aux ménages : financeur et liens vers les arbres, totaux par source, écarts entre sources, couverture départementale, sources, recherche préalable | € | 2019 à 2025 (CNAF, Unédic), 2020 à 2024 (DREES) | `prestations.py` | existant |
| `prestations/nationales.json` | `prestations_nationales.schema.json` | par prestation et par année : montant (chaque source), bénéficiaires, montant moyen, pensions par régime | €, foyers | idem | `prestations.py` | existant |
| `prestations/departements/<annee>.json` | `prestations_departement.schema.json` | par département : foyers, montant annuel, montant moyen (CAF) ; allocataires de l'Aspa (DREES) ; financeur du RSA | foyers, € | 2019 à 2025 | `prestations.py` | existant |
| `subventions/index.json`, `subventions/attribuants/<source>.json`, `subventions/annees.json`, `subventions/departements.json`, `subventions/beneficiaires.json`, `subventions/programmes.json` | `subventions_*.schema.json` | subventions au format des données essentielles des conventions (ADEME, Fonds vert, agence de l'eau Artois-Picardie, Culture, politique de la ville, FIR ARS Pays de la Loire, presse) : par source, année, département, programme LOLF ; bénéficiaires nommés (personnes morales), part agrégée | € | 2016 à 2026 selon la source | `subventions.py` | existant |
| `ue/contribution.json` | `ue_contribution.schema.json` | PSR-UE et son usage : rubriques et pôles du CFP 2021-2027, NextGenerationEU, engagements FTS 2024 par programme | Md€ | Exécution 2024 (PSR) ; CFP 2021-2027 | `ue.py` | existant |
| `ue/retours.json` | `ue_retours.schema.json` | dépenses de l'UE en France par année et rubrique, solde net (comptable, opérationnel) | Md€ | 2021 à 2025 | `ue.py` | existant |
| `ue/beneficiaires/index.json` | `ue_beneficiaires_index.schema.json` | bénéficiaires des fonds européens : couverture, totaux par source, année, région, département | € | Kohesio 2014-2027, FTS 2023-2025, Horizon Europe 2021-2026 | `ue.py` | existant |
| `ue/beneficiaires/<dep>.json` | `ue_beneficiaires_dep.schema.json` | bénéficiaires nommés d'un département (personnes morales) | € | idem | `ue.py` | existant |
| `niches/mesures.json` | `niches_mesures.schema.json` | chaque dépense fiscale : impôt, programme LOLF, coût par année, bénéficiaires, méthode, dates, note 2011 | M€ | PLF 2021 à 2026 (coûts 2019 à 2026) | `niches.py` | existant |
| `niches/programmes.json` | `niches_programmes.schema.json` | dépense budgétaire + dépense fiscale par programme, mission, grand poste | M€ | fiscal 2024 constaté, 2025-2026 estimés ; budget exécution 2024 | `niches.py` | existant |
| `niches/sociales.json` | `niches_sociales.schema.json` | niches sociales : exonérations, allègements, exemptions d'assiette ; série Urssaf par mesure | M€, Md€ | PLFSS 2026 (2023 à 2026) ; Urssaf 2019-2025 | `niches.py` | existant |
| `niches/index.json` | `niches_index.schema.json` | totaux par année, top, couverture du rattachement, sources, recherche préalable | divers | | `niches.py` | existant |
| `controle/index.json` | `controle_index.schema.json` | comptes, couverture ccomptes.fr, départements, sources inaccessibles, recherche publique | divers | | `controle.py` | existant |
| `controle/publications/programmes.json` | `controle_programmes.schema.json` | publications de la Cour reliées aux programmes (titre), NEB par mission | | 2011 à 2026 | `controle.py` | existant |
| `controle/publications/collectivites/<dep>.json` | `controle_collectivites.schema.json` | rapports des CRC reliés à la commune, l'EPCI, le département ou la région | | ROD 2015-2019 ; pages lues | `controle.py` | existant |
| `controle/publications/autres.json` | `controle_autres.schema.json` | publications non rattachées, non localisées | | | `controle.py` | existant |
| `controle/lobbying/organisations.json` | `controle_lobbying_organisations.schema.json` | représentants d'intérêts (organisations), dépenses déclarées par tranche, domaines, cibles | € (bornes) | exercices 2019 à 2026 | `controle.py` | existant |
| `controle/lobbying/ministeres.json` | `controle_lobbying_ministeres.schema.json` | actions déclarées par fonction et ministère visés, domaines, missions LOLF | actions | idem | `controle.py` | existant |
| `controle/aides_entreprises.json` | `controle_aides_entreprises.schema.json` | estimations publiées des aides aux entreprises (périmètre, année), exonérations Urssaf | Md€, € | estimations 2010-2026 (données 2019-2023) | `controle.py` | existant |
| `operateurs/operateurs.json` | `operateurs.schema.json` | opérateurs de l'État et catégories d'opérateurs : SCSP et autres financements de l'État, taxes affectées, ressources propres, masse salariale, ETPT, plafond d'emplois, budget initial, somme des dix plus hautes rémunérations, SIREN, programme chef de file | €, ETPT | exécution 2020 à 2024, LFI 2023 à 2025 | `operateurs.py` | existant |
| `operateurs/index.json` | `operateurs_index.schema.json` | totaux par année, couverture, sources, recherche préalable, limites | divers | | `operateurs.py` | existant |
| `comparaison/index.json`, `comparaison/depenses/*.json`, `comparaison/prelevements.json`, `comparaison/fiches.json` | `comparaison_*.schema.json` | la France et ses voisins : dépenses COFOG et prélèvements obligatoires, UE27, zone euro, 27 pays ; fiches par grand poste ; avertissements de comparabilité Eurostat | % du PIB, € par habitant, % du total | Eurostat 2000-2024 (dépenses), 2000-2025 (prélèvements) | `europe_comparaison.py` | existant |
| `affectation_prelevements.json` | `affectation_prelevements.schema.json` | ancien format prévu, remplacé à terme par `prelevements/affectation.json` | parts (0 à 1) | | | **prévu** |

Le millésime réel est toujours lu dans le fichier (`millesime`, `annee`, `annees`, clés d'année) ou dans `meta.json` (`millesime.etat_defaut`, `controle.exercice`, `controle.annee_cofog`, `controle.administrations_derniere_annee`, `controle.recettes_annees`, `controle.arbre_administrations.annee`) : le site ne code aucune année en dur.

### 2.1 `meta.json`

| Champ | Type | Sens |
|---|---|---|
| `millesime` | `{etat_defaut, etat_disponibles[], nature_etat}` | vue par défaut de l'arbre État et vues disponibles |
| `genere_le` | chaîne date-heure ISO 8601 | `meta.json` : fin du passage du pipeline ; **ne déclenche jamais de commit à lui seul** (workflow `data.yml`). Ailleurs (`niches/`, `secu/`, `decisions/`, millésimes « Sources collectées au »), date de la dernière collecte de l'entrepôt (`pipeline/reproductible.py`, `SOURCE_DATE_EPOCH` prioritaire) : deux productions sur le même entrepôt donnent des fichiers identiques |
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
| `tendance` | objet | `valeur` : `dans le sens souhaité publié`, `à l’inverse du sens souhaité publié`, `stable` (variation ≤ 1 % entre les deux dernières valeurs), `sens inconnu` ; `de_annee`, `a_annee`, `de`, `a`, `variation`, `variation_relative_pct` ; `justification` ou `raison` |
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
| `partis/<annee>.json` | `exercice` (entier), `ordre` (`regle`, `cles` : aide totale décroissante puis `nom_tri`), `partis[]` de `{code_cnccfp, nom, nom_tri, premiere_fraction_eur, seconde_fraction_eur, total_eur}` (`nom` = dénomination publiée, `nom_tri` = forme normalisée pour le tri), totaux, `definition`, `avertissements[]` (partis sans ventilation par fraction) |
| `scrutins/<scrutin>_<annee>.json` | agrégats seulement, **aucun candidat nommé** (le schéma interdit `candidat`/`candidats`) : `nombre_candidats`, `depenses_totales_eur`, `recettes_totales_eur`, `remboursement_etat_total_eur`, `apport_personnel_total_eur`, `dons_totaux_eur`, `decisions.<code CNCCFP>` (`{libelle, nombre}`, codes de la source gardés tels quels), comptes rejetés, hors délai, non déposés, `par_nuance[]` quand la source donne la nuance, `definitions`, `avertissements[]` |
| `candidats/<scrutin>_<annee>.json` | exception personnes physiques : `regle`, `champs[]`, `ordre` (circonscription puis nom, alphabétique) et `candidats[]` triés selon `ordre`. **Liste blanche** (`CHAMPS_CANDIDAT` du producteur, `additionalProperties: false` au schéma) : `candidat`, `nuance`, `parti`, `circonscription`, `tour`, `elu`, `depenses_eur`, `recettes_eur`, `apport_personnel_eur`, `dons_eur`, `remboursement_eur`, `decision`, `reference`. Ni adresse, ni date de naissance, ni donateur, ni mandataire financier. Publié seulement si `AFFICHER_CANDIDATS` ; le détail complet reste dans `data/processed/_restreint/` (jamais versionné) |

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

Lecture : `central` = hypothèse Insee de référence (taxes réparties comme la consommation) ; `bas`/`haut` = encadrement par la variante Insee où ces taxes sont imputées aux revenus. Ajustement voiture : remplacer `detail.ticpe.central` par `ticpe_si_voiture...` ou 0. Ajustement non-fumeur : retirer `detail.tabac`.

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

Producteurs : `pipeline/tracabilite.py` (sans réseau, lit `arbre/`, `nature/`, `beneficiaires/`, `vie_politique/`, `operateurs/` et le PLRG 2023) et `pipeline/decisions.py` (`jorf` : archive JORF de la DILA lue en flux, cache `data/lake/_cache/decisions_jorf/` ; `produire` : sans réseau). Montants en euros. Schémas : `tracabilite_noeud`, `tracabilite_resume`, `decisions_programme`, `decisions_amendements_resume`, `decisions_scrutins`, `decisions_mouvements`, `decisions_coherence_plrg`, `decisions_index`.

**Traçabilité (exécution 2024).** `tracabilite/programme_<n>.json` (un par programme de l'arbre) et `tracabilite/noeud_psr_<x>.json` (prélèvements sur recettes) ; `tracabilite/resume.json` : `global`, `grands_postes[]`, `missions[]`, `programmes[]`. Chaque nœud est partagé en quatre `parts` dont les `pct` somment à 100 :

| Part | Sens |
|---|---|
| `beneficiaire_identifie` | bénéficiaire nommé par une source publique (associations, marchés de l'État, France 2030, partis et remboursements de campagne, bénéficiaire unique désigné par le programme, Union européenne, subventions pour charges de service public 2024 aux opérateurs d'après le jaune « Opérateurs de l'État », réparties entre programmes financeurs par ajustement proportionnel sur leur catégorie 32, voir 2.21) ou catégorie fixée par la loi (collectivités : prélèvements, dotations 119 et 122) ; `niveau_identification` = `entite` ou `categorie` |
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
| `local/fonctions/<dep>.json`, `regions.json`, `index.json` | `local_fonctions_communes`, `local_fonctions_regions`, `local_fonctions_index` | dépenses par fonction (niveaux 1 et 2 + thèmes) de toutes les communes (statut `publie` ou `non_publie`), des EPCI (département du siège) et des régions, 3 derniers exercices (`pipeline/local_fonctions.py`, ou `local.py fonctions`) | DGFiP, balances nature-fonction (agrégées côté serveur) |
| `local/dotations/communes/<dep>.json`, `epci.json`, `departements.json`, `regions.json` | `local_dotations_*` | DGF et composantes, DCRTP, DILICO ; DETR/DSIL/DPV/DSID par projet | DGCL via OFGL, data.gouv |
| `local/taux/<dep>.json` | `local_taux` | taux votés par niveau (TFB, TFNB, THRS, TEOM), 3 exercices | DGFiP REI |
| `local/decisions/index.json`, `<siren>/index.json`, `<siren>/<annee>.json` | `local_decisions_*` | subventions votées par collectivité, couverture publiée | SCDL, Région Pays de la Loire, SIRENE |

Règles propres à ce bloc : on n'additionne jamais commune + EPCI (le bloc communal consolidé de l'OFGL sert à cela) ni département ou région au bloc communal. Bénéficiaires nommés : personnes morales seulement (`sirene.personne_morale`, groupements de personnes physiques exclus) ; le reste est agrégé dans `exclus_personnes_physiques_ou_non_identifies`. Les textes libres (objets de subvention, intitulés de projets, objets de délibération) sont remplacés par `null` s'ils contiennent une civilité ou un prénom suivi d'un nom.

Dépenses par fonction (`local/fonctions/`) : pour chaque collectivité et exercice (`annees.<AAAA>`, `null` si la présentation par fonction n'est pas publiée cet exercice), `nomenclature` (M57, M14 en 2023 pour une partie des communes, M71 pour quatre régions en 2023 : codes et libellés propres à chacune dans `index.json` `nomenclatures`, jamais mélangés), `population` (OFGL de l'exercice), `total`, `non_ventile`, `part_ventilee`, `f.<code>` (niveau 1 = 1 caractère, niveau 2 = 2 caractères) et `themes.<cle>` (écoles, voirie, culture, sport... : préfixes de codes par nomenclature dans `index.json` `themes`). Chaque valeur est un tableau aligné sur `colonnes` : euros de fonctionnement, euros d'investissement hors remboursements d'emprunts, les mêmes par habitant, puis les mêmes « sur 100 € » de dépenses totales (fonctionnement + investissement) de la collectivité. Méthode : formules OFGL des agrégats « Dépenses de fonctionnement » (DN6 − DN675 − DN676 − DN68 − DN65882) et « Dépenses d'investissement hors remb », appliquées à chaque code de fonction, budget principal seulement ; budgets votés par fonction : chapitres 90<f>/93<f> lus comme la fonction <f>, chapitres 92x/94x/95x rattachés à 01. Une commune sans présentation par fonction (facultative sous 3 500 habitants) a le statut `non_publie` : aucune estimation n'est publiée. `index.json` `communes.<insee>` : masque (1 commune, 2 EPCI, 4 région) ; `couverture.<AAAA>` : communes publiées, part de la population, EPCI, régions.

Année d'une subvention (`<siren>/<annee>.json`) : SCDL, année de la date de décision ou de convention, à défaut colonne d'année, puis année du jeu ; Région Pays de la Loire, préfixe du numéro d'opération, à défaut année d'exécution du mandatement. Faute de toute année, la ligne va dans `<siren>/inconnue.json` (`annee` = `"inconnue"`), jamais rattachée à une année devinée. Région Pays de la Loire : une opération à plusieurs tiers est attribuée au SIRET le plus mandaté (à égalité, le plus petit SIRET) et retirée des noms si l'un de ses tiers est une personne physique ; les mandatements sans numéro d'opération sont regroupés par SIRET et année d'exécution, sans vote (`mandatements_sans_operation` dans `<siren>/index.json`). Toute sélection est faite par un tri explicite sur des clés déterministes : deux productions sur le même entrepôt donnent des fichiers identiques octet pour octet (`tests/test_reproductibilite.py`).

### 2.16 Sécurité sociale et protection sociale : `secu/` (contrat 1.5)

Producteur : `pipeline/secu.py` (arbres construits par le module générique `pipeline/arbre.py`). Chaque fichier porte `millesime`, `source` et `unite` (Md€). Commandes : `python pipeline/secu.py collecter` (réseau, reprenable ; un refus 401/403/429 est noté, jamais contourné ; OCR des tableaux publiés en image, mis en cache dans `data/lake/secu/_ocr_secu/`), `python pipeline/secu.py produire` (sans réseau). Tests : `pytest tests/test_secu.py`.

```
data/lake/secu/ (PLACSS 2024 texte et annexes 1, 3, 4, 7 ; PLACSS 2025 texte ; DSS Chiffres clés 2024 ;
                 Unédic data.gouv.fr ; DREES comptes de la protection sociale)
     └─> pipeline/secu.py (arbre.construire) ─> site/data/secu/arbre/, arbre_2025/, cps/, index.json
```

Deux comptabilités, jamais additionnées : `arbre` et `arbre_2025` suivent les comptes des organismes (droits constatés : tableau d'équilibre par branche des régimes obligatoires de base, ONDAM, comptes du FSV et de la CADES, compte consolidé des régimes complémentaires, Unédic) ; `cps` suit les comptes de la protection sociale de la DREES (base comptabilité nationale, prestations seulement, tous financeurs).

| Vue | Niveaux | Total | Traçabilité directe |
|---|---|---|---|
| `arbre` (Exécution 2024) | `organisme` (régimes de base et FSV, retraites complémentaires, Unédic, CADES) > `branche` (ou poste) > `poste` > `sous_poste` > `detail` | 827,9 Md€ | 78,8 % |
| `arbre_2025` (Exécution 2025) | `organisme` > `branche` (ou poste) | 727,5 Md€ (sans les retraites complémentaires, non publiées) | 95,1 % |
| `cps` (2024) | `secteur` > `regime` > `risque` > `sous_risque` > `groupe` > `prestation` > `detail` ; découpe après `regime` | 933,2 Md€ | 100 % |

Nœud : champs de l'arbre État (2.2 : `id`, `nom`, `niveau`, `md`, `enfants` ou `fichier` + `nb_enfants`, chemin relatif à `site/data/`), plus :

| Champ | Type | Sens |
|---|---|---|
| `sources` | tableau de clés | sources du montant ; détail (titre, URL, licence, millésime, verdict) dans `sources_detail` de la racine et `sources` de `index.json` |
| `tracabilite_pct` | nombre (0 à 100) | part du montant (en valeur absolue) lue directement dans une source (`publie` ou `tableau_image`) |
| `mode` | feuille seulement | `publie` (texte ou jeu ouvert), `tableau_image` (tableau publié en image, revérifié par OCR ou somme de contrôle), `derive` (part publiée × total, différence, arrondis ou non-ventilé de la source), `ecart` (différence de champ entre deux sources) |
| `modes_md` | nœud intermédiaire | montant par mode |
| `note`, `ref` | chaînes | calcul d'un montant dérivé ; page de la source |
| `ecarts[]` | `{source, md, libelle}` | autre montant publié pour le même agrégat (`md` à `null` : comparaison renvoyée à une autre vue), jamais lissé |
| `destinataire` | chaîne | identifiant de `prelevements/affectation.json` (`cnam`, `branche_atmp`, `cnav`, `cnaf`, `cnsa`, `agirc_arrco`, `unedic`, `cades`) : relie un prélèvement au nœud qui le dépense |

Un montant négatif est une déduction publiée : transferts entre branches et avec le FSV (comptés deux fois dans les branches), remises sur les médicaments, clause de sauvegarde. Un écart de champ est un nœud `ecart` (ex. `robss/maladie/hors_ondam` : charges de la branche moins sous-objectifs ONDAM). Contrôles (`tests/test_secu.py`) : chaque nœud = somme de ses enfants, montants du PLACSS retrouvés, `tracabilite_pct` recalculable depuis les feuilles, destinataires connus d'`affectation.json`.

**`secu/index.json`** : `vue_defaut`, `vues.<vue>` (`millesime`, `fichier`, `total_md`, `noeuds`, `feuilles`, `profondeur`, `fichiers`, `tracabilite_pct`, `modes_md`), `liens_affectation`, `verification_documents` (chaque document : `vérifié` ou absent ; la production échoue si un montant saisi n'est plus dans le document), `sources`, `sources_inaccessibles[]` (`{source, motif}`), `recherche_publique` (`trouvailles[]` : verdict `réutilisable tel quel`, `à adapter` ou `inspiration seulement`, licence, date du dernier commit ou de mise à jour).

### 2.17 Union européenne : `ue/` (contrat 1.5)

Producteur : `pipeline/ue.py`. Chaque fichier porte `millesime` et `source`. Commandes : `python pipeline/ue.py collecter` (réseau ; un refus 403/429 est noté, jamais contourné), `python pipeline/ue.py resoudre --budget <s>` (réseau, reprenable : noms Kohesio vers SIREN, SIREN vers catégorie juridique), `python pipeline/ue.py produire` (sans réseau). Tests : `pytest tests/test_ue.py`.

```
data/lake/europe/ue_documents/ (annexe PLF 2025 « Relations financières avec l'UE », notes du Sénat PLF 2026 et 2027)
data/lake/_restreint/europe/ue/ (Kohesio France 2014-2020 et 2021-2027, FTS 2023-2025)
data/lake/europe/esr__fr-esr-horizon-projects-entities.parquet (Horizon Europe, MESR)
+ site/data/arbre/racine.json (branche « Prelevements sur recettes/Union européenne »)
+ API Recherche d'entreprises (catégorie juridique, rapprochement des noms Kohesio ; caches data/lake/_cache/)
     └─> pipeline/ue.py ─> site/data/ue/contribution.json, retours.json, beneficiaires/index.json, beneficiaires/<dep>.json
```

Les chiffres saisis depuis les PDF (CFP, retours, soldes, PSR) sont revérifiés à chaque `produire` contre le texte du PDF (`verification_documents`) : un document modifié fait échouer la production. Le PSR-UE de `contribution.json` est lu dans l'arbre État et doit égaler l'exécution 2024 publiée (22 276 M€).

**`ue/contribution.json`** (ce qui part)

| Champ | Type | Sens |
|---|---|---|
| `psr_ue` | `{annee, md, noeud_arbre, fichier_arbre, eur_sur_100_budget_etat, source}` | prélèvement sur recettes au profit de l'UE, nœud de l'arbre État |
| `serie_psr_ue[]` | `{annee, vote_md, execute_md, statut, source}` | PSR voté et exécuté 2018 à 2026 (`statut` : `exécuté` ou `prévision d'exécution`) |
| `usage.rubriques[7]` | `{code, nom, cfp_md, plafond_rubrique_md, part, contribution_france_md, eur_sur_100, poles[]}` | répartition conventionnelle du PSR au prorata des pôles du CFP 2021-2027 (marges exclues, `marges_exclues_md`) ; `poles[]` mêmes champs (PAC = pôle `8`) |
| `next_generation_eu` | `{total_md, par_rubrique_md, note, source}` | plan de relance, financé par l'emprunt, hors PSR |
| `programmes_engagements` | `{millesime, source, perimetre, total_md, programmes[], autres}` | engagements FTS 2024 de toute l'UE par programme (`code` du CFP, `rubrique`, `md`, `part`, `dont_france_md`), gestion directe et indirecte seulement |
| `contribution_comptable_2024_md` | nombre | PSR + droits de douane reversés (méthode comptable) |
| `sources_inaccessibles[]` | `{source, url, constat, effet}` | sources refusées (429, 404), non contournées |

Lecture : `eur_sur_100` = « sur 100 € versés par la France au budget de l'UE, X € correspondent à cette politique » ; c'est la structure du budget de l'UE, pas un fléchage (avertissement publié).

**`ue/retours.json`** (ce qui revient, solde net) : `annees[]` de `{annee, retours_md, par_rubrique, rubriques_completes, solde_net_comptable_md, solde_net_pct_rnb, contribution_comptable_md, psr_ue_execute_md, solde_net_operationnel_md?, source}`. `par_rubrique.<code>` = `{nom, md}` ; complet pour 2021-2023 (Commission, rapports financiers), partiel pour 2024 (PAC, compétitivité, cohésion) et 2025 (PAC). `contribution_comptable_md = retours_md - solde_net_comptable_md` (déduite). Retours hors NextGenerationEU. `methodes_solde` décrit les méthodes comptable, opérationnelle (Commission) et de la correction britannique ; `beneficiaires_nommes` résume `ue/beneficiaires/index.json`.

**`ue/beneficiaires/index.json`** : `sources.<kohesio_2014_2020|kohesio_2021_2027|fts|horizon>` = `{total, nomme, lignes, titre, exclus_*, hors_total_*}` ; conservation : `nomme + somme(exclus_*) = total` (testé) ; `hors_total_*` (PAC non collectée, facilité pour la reprise NextGenerationEU) est hors total. `par_annee.<source>.<année>`, `par_region[]`, `departements[]` (`{code, nom, region, fichier, beneficiaires, total_eur, nomme_eur}`, `non_localise` compris), `total_eur`, `total_nomme_eur`, `part_nommee`, `beneficiaires_nommes` (SIREN distincts), `recherche_publique[]` (verdict : `réutilisable tel quel`, `à adapter`, `inspiration seulement`, licence, date), `sources_inaccessibles[]`. Les totaux excluent `horizon`, qui recoupe le programme FTS 1.0.11.

**`ue/beneficiaires/<dep>.json`** (départements de l'API Découpage administratif, et `non_localise`) : `{departement, nom, region: {code, nom} | null, totaux.<source>: {total_eur, nomme_eur, non_nomme_eur}, beneficiaires[], beneficiaires_hors_fichier?}`. Un bénéficiaire : `{siren, denomination, categorie_juridique, montant_eur, montant_hors_horizon_eur, detail[]}` ; `detail[]` = `[source, année, fonds ou programme, montant_eur, lignes]`. Rattachement au département : lieu de l'opération (Kohesio : commune LAU, sinon NUTS 3), code postal du bénéficiaire (FTS), département d'activité (Horizon), à défaut siège SIRENE.

Années : Kohesio = année de début de l'opération, montant = budget UE programmé de l'opération ; FTS = année d'engagement, montant contracté ; Horizon = année de l'appel, subvention signée.

**Personnes physiques (bloquant).** Seules les personnes morales (catégorie `2xxx` à `9xxx`, vérifiée via l'API) sont nommées, sous leur dénomination SIRENE (jamais le nom brut de la source). Les noms Kohesio sont rapprochés d'un SIREN par l'API (même département, mots du nom identiques ou quasi identiques, résultat ambigu rejeté) ; un nom non rapproché, un entrepreneur individuel (`1000`) ou une ligne FTS « Private Persons » est agrégé (`exclus_*`). Les bénéficiaires de la PAC (FEAGA, FEADER, programmes FTS `3.1.x`) ne sont pas collectés. Les listes brutes restent dans `data/lake/_restreint/`.

### 2.18 Dépenses fiscales et niches sociales : `niches/` (pipeline/niches.py)

Producteur : `pipeline/niches.py`. Chaque fichier porte `millesime` et `source`. Commandes : `python pipeline/niches.py collecter` (réseau ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/niches.py produire` (sans réseau ; `pdftotext` de poppler-utils requis). Tests : `pytest tests/test_niches.py`.

```
data/lake/etat/ et data/lake/fiscalite/ (classeurs DGFiP Voies et moyens tome II, PLF 2021, 2022, 2023, data.economie)
data/lake/fiscalite/niches_vm/ (tomes II PLF 2024, 2025, 2026 en PDF, miroirs Assemblée nationale ; PLFSS 2026 annexe 4 ;
                                notes du comité d'évaluation 2011)
data/lake/aides_entreprises/ (Urssaf, exonérations par mesure)  + site/data/arbre/racine.json (exécution 2024)
     └─> pipeline/niches.py ─> site/data/niches/mesures.json, programmes.json, sociales.json, index.json
```

Une année est lue dans l'édition la plus récente qui la chiffre : PLF N+2 (réalisation, `statut` « constaté ») jusqu'en 2024, PLF 2026 pour 2025 et 2026 (« estimé »). Les montants restent en millions d'euros comme à la source. Contrôle bloquant : pour 2022, 2023 et 2024, la somme des fiches retrouve le total publié par la DGFiP à 1 M€ près (85 616, 82 923, 89 406 M€) ; pour 2025 et 2026 l'écart est publié (`ecart_meur`) : le total officiel impute une prévision aux mesures dont la fiche porte « nc ».

**`niches/mesures.json`** : `mesures[]` de `{id (6 chiffres), libelle, impot, sous_categorie, editions[], finalite, norme, reference, methode, fiabilite, programme, programmes_subsidiaires?, beneficiaires, dates, couts, evaluation_2011?}`.

| Champ | Type | Sens |
|---|---|---|
| `couts.<année>` | `{brut, meur, statut, plf, hors_reference?}` | `brut` tel que publié ; `meur` en M€, **null** pour « nc » (non chiffré), « ε » (moins de 0,5 M€), « - » (aucun effet budgétaire), jamais 0 ; `plf` = édition lue ; `hors_reference` : mesure absente de l'édition de référence de l'année (supprimée, renumérotée), dernière prévision gardée, hors totaux |
| `programme` | `{code, libelle, plf, noeud_arbre}` ou null | programme de rattachement principal (tome II) ; `noeud_arbre` = `id` du nœud de `arbre/racine.json` (null si absent de l'arbre) |
| `beneficiaires` | `{nombre, nature, brut?, plf}` | nombre publié (ménages, entreprises, locaux...) ; `brut` si non chiffré (« Non déterminé ») |
| `dates` | `{creation, modification, fin_fait_generateur, fin_incidence, suppression?, plf}` | années ou « non borné » |
| `evaluation_2011` | `{note, brut, cout_2011}` | note 0 à 3 du comité d'évaluation des dépenses fiscales et des niches sociales (IGF, 2011) ; `note` null si non évaluée |

**`niches/programmes.json`** : `programmes[]` (`programme`, `noeud`, `nom`, `mission`, `grand_poste`, `mesures[]`, `fiscal_meur.<2024|2025|2026>`, `non_chiffrees.<année>`, `budget_meur` = exécution 2024 de l'arbre, `total_2024_meur`, `part_fiscale_2024`), `missions[]` et `grands_postes[]` (mêmes sommes), `hors_arbre[]` (programme absent de l'arbre), `couverture` (part du coût 2024 rattachée à un programme de l'arbre). Dépense fiscale (perte de recettes estimée) et dépense budgétaire (décaissement) s'additionnent pour lire l'effort par politique, sans se confondre.

**`niches/sociales.json`** : synthèse ROBSS (annexe 4, tableau 6, Md€), `allegements_et_exonerations_compensees` (tableau 13) et `exonerations_non_compensees` (tableau 14) : `lignes[]` de `{libelle, niveau (groupe, mesure, dont), mission (crédits qui compensent), meur.<2024|2025|2026>, brut?, statut}` ; `exemptions_assiette` (tableau 9 : assiette exemptée, cotisations équivalentes brutes et nettes, 2023-2026, Md€) ; `urssaf` (série 2019-2025 par mesure, secteur privé). Les exonérations compensées par crédits budgétaires figurent déjà dans la dépense de l'État : elles ne s'ajoutent pas aux dépenses fiscales.

**`niches/index.json`** : `totaux.<année>` (`plf_reference`, `statut`, `chiffre_meur`, `mesures`, `chiffrees`, `nc`, `epsilon`, `sans_effet`, `hors_reference`, `total_publie_meur`, `ecart_meur`), `top_2025[]`, `par_impot_2025[]`, `couverture_programmes`, `niches_sociales`, `beneficiaires_nommes` (aucun : secret professionnel en matière fiscale, crédit d'impôt recherche compris ; agrégats seulement), `verification_documents`, `sources`, `sources_inaccessibles[]` (budget.gouv.fr : 403, non contourné), `recherche_publique[]` (verdict, licence, date).

### 2.19 Dette publique : `dette/` (pipeline/dette.py)

Producteur : `pipeline/dette.py`. Commandes : `python pipeline/dette.py collecter` (réseau : API Insee BDM, Eurostat JSON-stat, BCE ; rapports du Sénat ; vers `data/lake/dette/_api/` ; un refus 401/403/429 ou une page Cloudflare est noté, jamais contourné), `python pipeline/dette.py produire` (sans réseau ; échoue si une citation reprise d'un document n'y figure plus). Tests : `pytest tests/test_dette.py`. Tous les fichiers sont compacts, portent `millesime`, `source`, `unite` (Md€), `avertissement`, et pour chaque série sa source, sa date de mise à jour et sa définition.

```
Insee BDM (DETTE-TRIM-APU-2020, DETTE-NEGOCIABLE-ETAT) ─┐
Eurostat (gov_10dd_edpt1, gov_10dd_ggd, gov_10a_main, nama_10_gdp), BCE (GFS, PSPP, PEPP) ─┤
data/lake (Insee DD_CNA_APU, PLACSS), Sénat (PLF 2026, PLF 2027, rapport n° 902) ─┼─> pipeline/dette.py ─> site/data/dette/*.json
site/data (realisations/117.json, arbre/racine.json, secu/) ─┘
```

Deux comptabilités, jamais additionnées : **budgétaire** (programme 117, crédits consommés) et **nationale** (D41, intérêts dus, et dette au sens de Maastricht). Les écarts entre sources sont listés dans `ecarts[]` (valeurs des deux sources, écart, explication si la source en donne une), jamais lissés. Années en chaînes (`"2025"`).

| Fichier | Contenu |
|---|---|
| `dette/encours.json` | dette de Maastricht fin d'année, 2000 à la dernière année publiée : `insee.<Etat|ODAC|APUL|ASSO|Ensemble>` (`idbank`, `md`, `pct_pib` calculé avec le PIB Eurostat, `dernier_trimestre`, et pour l'ensemble `pct_pib_publie`) ; `eurostat.<S13|S1311|S1313|S1314>` (`md`, `pct_pib` publié ; sous-secteurs depuis 2021) ; `bce.secteurs` (séries longues des sous-secteurs) ; `ecarts[]` (Insee publie la contribution de chaque sous-secteur à la dette consolidée, Eurostat la dette du sous-secteur consolidée en son sein seulement) |
| `dette/interets.json` | `budgetaire.annees.<2000..2026>` (`md` ou `null` avec `motif`, `statut` : exécution, trou, LFI ; exécution reprise de `realisations/117.json`) et `previsions` ; `nationale.eurostat.secteurs` (D41PAY, `pct_pib`, `part_depenses` = intérêts / dépenses totales) et `nationale.insee.secteurs` (D41 de l'État et des ODAC séparés) ; `cas_type` ; `sensibilite` (choc de +1 point, AFT via Sénat) ; `rendements_moyens_pct` (BCE) |
| `dette/detenteurs.json` | `eurostat.<S2|S121|S122_S123|S124-S129|S11_S14_S15>` (`md`, `part`) et `bce` (même ventilation, série longue depuis 2000), `controle_somme_derniere_annee`, `eurosysteme_achats_nets_cumules` (PSPP, PEPP : valeur comptable, Eurosystème entier), `banque_de_france_publie` (part des non-résidents, définition Banque de France) ; les assureurs ne sont pas isolés par la source, les ménages pas séparés des sociétés non financières |
| `dette/financement.json` | `dette_negociable_etat` (encours fin décembre, court terme, moyen et long terme, taux fixe, indexée sur l'inflation, `part_indexee`, `dernier` mois) ; `programme_financement_etat.annees` (émissions nettes des rachats, amortissements dont indexation, déficit, besoin de financement : exécution 2024, LFI et révisé 2025, LFI 2026, PLF 2027) ; `titres_apu_bce` (émissions et remboursements bruts annuels, maturité résiduelle et initiale moyennes, toutes APU) |
| `dette/index.json` | `fichiers`, `synthese` (dernière année), `dette_sociale` (ASSO, situation nette et amortissement de la CADES, passif net de la sécurité sociale, `liens_secu[]` vers les nœuds `cades` de `secu/` sans dupliquer leurs montants), `verification_documents`, `sources_inaccessibles[]`, `recherche_publique.trouvailles[]` (verdict, licence, date) |

**Part de 100 € d'impôt qui paie des intérêts** (`interets.json` → `cas_type`) : cas C04 (2 100 € net, célibataire, locataire). Répartition par administration de ce que paie le foyer calculée avec le module du site appelé comme l'écran résultat (`web/src/ecrans/saisie.ts` : `calculer`, `assembler`, `parAdministration`), sur le périmètre de la carte : prélevé sur salaire et IR, taxes sur la consommation centrales, TEOM de la commune. Variante principale : locataire à Lyon (69123), 13 891,94 € par an comme la carte ; `variantes` publie aussi Nantes (commune du cas type) et « sans commune » (TEOM non chiffrée, 0 €), seule différence entre elles ; chaque part est multipliée par la part des intérêts dans les dépenses de l'administration qui la reçoit (comptabilité nationale, dernière année). `lecture_budgetaire_etat` donne à part la place du programme 117 dans l'arbre État : les deux lectures ne s'additionnent pas.

### 2.20 Contrôle, influence, aides aux entreprises : `controle/` (pipeline/controle.py)

Producteur : `pipeline/controle.py`. Chaque fichier porte `millesime` et `source`. Commandes : `python pipeline/controle.py collecter --budget <s>` (réseau, reprenable : pages ccomptes.fr listées par `sitemap_publication`, arrêt au premier 403/429 ou après 5 erreurs serveur consécutives, jamais contourné ; catégorie juridique des SIREN du répertoire HATVP, cache `data/lake/_cache/recherche_entreprises_controle.json`), `python pipeline/controle.py produire` (sans réseau). Tests : `pytest tests/test_controle.py`.

```
data/lake/controle/ (métadonnées ROD des CRC 2015-2019 et publications de la Cour 2011-2016, data.gouv.fr ;
                     rapport HCSP « Les aides aux entreprises », juillet 2026)
data/lake/_cache/ccomptes/ (pages publications lues, flux RSS)  data/lake/_restreint/politique/ (répertoire HATVP)
data/lake/aides_entreprises/ (exonérations Urssaf)  + site/data/realisations, beneficiaires, local/geo, niches, ue
     └─> pipeline/controle.py ─> site/data/controle/index.json, publications/, lobbying/, aides_entreprises.json
```

**Contrôle.** Une publication : `{id, titre, date, annee, type, juridiction, url, url_document?, source}` et, selon la source, `famille`, `nature_controle`, `document` (fichier de l'archive data.gouv.fr), `constats_chiffres[]` (`{montant, valeur_eur, extrait}` : phrases du résumé publié contenant un montant). Jamais le titre d'une réponse ni un résumé contenant une civilité. `publications/programmes.json` : `programmes.<n>` (`publications[]` = identifiants, `neb_mission`), `neb_par_mission` (notes d'exécution budgétaire vérifiées par `realisations.py`, reprises par lien), `publications[]` avec `programmes[]`, `operateurs[]` (`{operateur, programme}`) et `rattachement[]` : titre contenant le nom exact du programme (deux mots significatifs au moins ; demandeur « (Assemblée nationale) », « (Sénat) » retiré), de la mission (trois mots au moins) ou d'un opérateur dont le programme est chef de file (trois mots au moins). `publications/collectivites/<dep>.json` (et `region_<code>.json` pour une région) : `niveau` (`commune`, `epci`, `departement`, `region`, `autre_organisme` rattaché à son lieu) et `codes` `{commune, epci, departement, region}` du COG en vigueur (`local/geo`) ; un EPCI ou une commune disparus depuis le rapport gardent le seul code du département (`rattachement` le dit). `publications/autres.json` : publications non rattachées et `non_localisees` (collectivités d'outre-mer hors COG, lieu illisible). Les pages ccomptes.fr non lues ne sont pas publiées : `index.json` donne `couverture_ccomptes` (pages au plan du site, pages lues).

**Influence.** `lobbying/organisations.json` : tableau `organisations[]` selon `colonnes` (`identifiant`, `type_identifiant` SIREN/RNA/HATVP, `denomination`, `categorie`, `secteurs`, `depenses_declarees` = `[annee, borne_basse_eur, borne_haute_eur]` (null : tranche ouverte « ≥ 10 M€ »), `activites`, `actions`, `domaines` et `cibles` (5 premiers, `[libellé, nombre]`), `missions_lolf`), `totaux_par_annee` (somme des bornes ; `depense_max_eur` null s'il existe une tranche ouverte), `exclus` (comptes par motif). `lobbying/ministeres.json` : `cibles[]` (`{fonction, cible, actions, organisations, par_annee, domaines, missions_lolf}`), `domaines[]`, `correspondance_ministere_missions` (conventionnelle, établie par le projet). Année d'un exercice : année de sa date de fin.

**Aides aux entreprises.** `aides_entreprises.json` : `estimations[]` (`{id, auteur, annee_publication, annee_donnees, annee_donnees_note?, publication, variante?, md, md_haut?, perimetre, inclut, exclut, composantes_md?, source}` ; `publication` est toujours le titre réel, la variante de périmètre est dans `variante` ; `annee_donnees_note` explique une année absente), `types` (subventions, dépenses fiscales classées et déclassées, exonérations de cotisations, prêts et garanties, collectivités, Europe), `fourchette` (plus basse et plus haute estimation, avec la raison de l'écart), `exonerations_cotisations_urssaf.annees[]` (secteur privé, par grande catégorie, 2004 à 2025), `donnees_du_site[]` (liens vers `beneficiaires/`, `niches/`, `ue/`, sans copie), `verification_documents` (chaque montant est retrouvé dans le rapport du HCSP à chaque production, sinon la production échoue). Les estimations ne sont ni additionnées ni départagées.

**Personnes (bloquant).** Aucune personne physique : ni dirigeants, collaborateurs, clients ou affiliations du répertoire HATVP (vues jamais lues), ni responsables publics (fonction et ministère ou institution seulement ; texte libre contenant un nom remplacé par « texte libre non publié »), ni auteurs des réponses aux rapports. Organisation HATVP nommée seulement si sa catégorie juridique est `2xxx` à `9xxx` (`sirene.personne_morale`), si elle est inscrite au RNA, ou, à identifiant HATVP, hors catégories « indépendant ». Déclarations de patrimoine et d'intérêts de la HATVP : exclues. Légifrance : non utilisé.

### 2.21 Opérateurs de l'État et agences : `operateurs/` (pipeline/operateurs.py)

Producteur : `pipeline/operateurs.py`. Source : annexe « Opérateurs de l'État » (jaune) aux PLF 2024, 2025 et 2026, en PDF, lue sur le miroir officiel de l'Assemblée nationale (budget.gouv.fr refuse les scripts, 403, non contourné) ; liste data.gouv.fr des opérateurs et catégories (PLF 2024 à 2026) pour le statut, les membres et le programme chef de file ; SIREN par dénomination identique (API Recherche d'entreprises, personnes morales de droit public ou EPIC seulement). Commandes : `python pipeline/operateurs.py collecter` (réseau), `python pipeline/operateurs.py siren` (réseau, ≤ 4 appels/s, cache `data/lake/_cache/operateurs_siren.json`), `python pipeline/operateurs.py produire` (sans réseau, cache d'analyse `data/lake/_cache/operateurs/`). Tests : `pytest tests/test_operateurs.py`.

```
data/lake/etat/an__jaune_operateurs_plf<2024|2025|2026>/ (PDF) + listes data.gouv.fr
     └─> pipeline/operateurs.py (pdfplumber) ─> site/data/operateurs/operateurs.json, index.json
                                                     └─> pipeline/tracabilite.py (SCSP 2024, catégorie 32)
```

`operateurs.json` : `operateurs[]`, une entrée par ligne du jaune (`niveau` = `operateur` ou `categorie` ; une catégorie liste ses `membres[]` `{nom, statut, siren, categorie_juridique, dix_plus_hautes_remunerations_eur}`) avec `id` (sigle ou nom normalisé, stable d'un jaune à l'autre), `nom`, `sigle`, `statut`, `programme_chef_de_file`, `siren`, `categorie_juridique`, `siren_methode`, et `annees.<AAAA>` :

| Champ | Sens |
|---|---|
| `nature` | `execution` (RAP, repris par le jaune N+2 ; le plus récent fait foi) ou `lfi` (crédits votés seulement : 2025) |
| `financement_etat` | exécution par catégorie : `scsp` (titre 3, cat. 32), `sci` (titre 5, cat. 53), `dfp` (titre 7, cat. 72), `transferts` (titre 6), chacune `{ae_eur, cp_eur}` ; `financement_etat_total_cp_eur` |
| `credits_votes_lfi` | même découpage, LFI de l'année (2023 à 2025) ; `credits_votes_lfi_total_cp_eur` |
| `programmes_financeurs` | programmes cités par le jaune pour l'opérateur (toutes catégories ; la SCSP n'est pas ventilée par programme) |
| `taxes_affectees_eur`, `taxes_affectees_prevision_eur` | exécution (source en M€) ; prévision 2025 (source en €) |
| `ressources_propres_eur`, `masse_salariale_eur` | exécution, comptabilité générale |
| `etpt_sous_plafond`, `etpt_hors_plafond`, `plafond_emplois_lfi` | ETPT exécutés ; plafond voté (sous plafond, LFI) |
| `budget_initial` | `{charges_eur, produits_eur}` du compte de résultat prévisionnel (budget initial de l'année) |
| `dix_plus_hautes_remunerations_eur` | somme des dix plus hautes rémunérations brutes (article 179 de la loi de finances pour 2020) ; jamais de montant individuel ni les commentaires de la source |
| `sources` | jaune d'où vient chaque champ (`jaune PLF AAAA`) |

`remunerations_non_rattachees[]` : entités de la table des rémunérations dont la dénomination ne correspond à aucune ligne (publiées telles quelles, sans rapprochement approximatif). `index.json` : `totaux.<AAAA>` (sommes des lignes), `couverture` (lignes, catégories, opérateurs de la liste 2026, SIREN résolus, années), `sources`, `recherche_prealable[]` (verdict, licence, date), `limites[]`, `unites_source`. Contrôle de lecture : chaque tableau du jaune doté d'une ligne « Total » est retrouvé à 5 k€ ou 0 ETPT près. 2019 : non couvert (jaunes PLF 2021 à 2023 absents des miroirs officiels).

### 2.23 La France et ses voisins : `comparaison/` (pipeline/europe_comparaison.py)

Producteur : `pipeline/europe_comparaison.py`. Sources déclarées dans `collecte/catalogue.json` (`eu_comparaison_*`, domaine `europe`) et collectées par `python collecte/collecte.py eu_comparaison_cofog_pib eu_comparaison_cofog_part eu_comparaison_cofog_meur eu_comparaison_taxag eu_comparaison_population eu_comparaison_pib eu_comparaison_documents` (réseau ; un refus 401/403 n'est jamais contourné) ; `python pipeline/europe_comparaison.py produire [--sortie DOSSIER]` (sans réseau ; échoue si une citation Eurostat n'est plus dans le document collecté). Tests : `pytest tests/test_europe_comparaison.py`. Fichiers compacts, avec `millesime`, `source`, `unite`, `avertissement`.

```
Eurostat gov_10a_exp (S13, TE ; PC_GDP, PC_TOT, MIO_EUR) ─┐
Eurostat gov_10a_taxag (S13_S212), nama_10_pe, nama_10_gdp ─┼─> pipeline/europe_comparaison.py ─> site/data/comparaison/*.json
métadonnées et articles Eurostat (citations vérifiées) ─────┘
```

Couverture : France, UE à 27 (`EU27_2020`), zone euro (`EA20`) et les 27 pays ; dépenses 2000 à la dernière année publiée par au moins 25 pays (COFOG niveaux 1 et 2), prélèvements 2000 à la dernière année. Trois unités par série, alignées sur `annees` : `pct_pib` (publié), `part_total` (publié pour les dépenses, calculé pour les prélèvements), `eur_hab` (calculé : millions d'euros / population nama_10_pe, euros courants sans correction des prix). `null` = valeur non publiée. `statuts.<geo>.<code>` : années « p » (provisoire) et « b » (rupture de série) publiées par Eurostat.

| Fichier | Contenu |
|---|---|
| `comparaison/index.json` | `pays[]` (`geo`, `nom`, `nom_tri`, ordre alphabétique affiché dans `ordre`), `agregats[]`, `unites`, `depenses.fichiers[]` (lien `fichier`), `controle_somme_divisions`, `prelevements`, `fiches`, `avertissements[]` (`id`, `theme` : périmètres, prestations fiscalisées, systèmes de retraite, révisions ; `texte` en français, `citation` exacte en anglais, `source.url`, `source.document`), `verification_documents`, `sources` (mise à jour Eurostat de chaque jeu), `collecte_le`, `recherche_publique.trouvailles[]` (verdict, licence, date) |
| `comparaison/depenses/<code>.json` | `code` = `TOTAL` ou une division `GF01` à `GF10` : une division COFOG et ses groupes : `fonction`, `sous_fonctions[]`, `annees`, `geos`, `series.<geo>.<code>.<unité>[]`, `statuts` |
| `comparaison/prelevements.json` | impôts et cotisations sociales obligatoires (secteur S13_S212, y compris impôts versés aux institutions de l'UE) : `categories[]` (`code`, `nom`, `signe` dans l'identité, `parent` pour un « dont »), `identite` (total = D2 + D5 + D91 + D611C + D613C − D995, écart maximal relevé), `series`, `statuts`, `note` (différence avec le taux de l'Insee) |
| `comparaison/fiches.json` | une fiche par grand poste (santé GF07, retraites GF1002 avec survivants GF1003 en `voir_aussi`, éducation GF09, défense GF02, ordre public GF03, transports GF0405, logement GF0601 + GF1006, environnement GF05, intérêts de la dette GF0107) et deux repères (`depenses_totales`, `prelevements_obligatoires`) : `annee`, `france`, `ue27`, `zone_euro`, `mediane_ue_pct_pib` (médiane non pondérée des pays publiés), `ecart_mediane_points_pib`, `rang`/`rang_sur`, `evolution_10_ans`, `pays_par_valeur[]`, `mode` (publié ou calculé), `avertissements[]` (identifiants de `index.json`) |

**Neutralité.** Aucun qualificatif de niveau (« trop », « pas assez », couleurs de classement) : un rang, une médiane, un écart en points, une évolution. Ordre des pays : alphabétique (`index.json`) ou par valeur décroissante puis nom (`fiches.json`), règle écrite dans `ordre.regle`. Rang 1 = valeur la plus haute ; valeurs égales, même rang.

### 2.24 Prestations versées aux ménages : `prestations/` (pipeline/prestations.py)

Allocations familiales, aides personnelles au logement (APL, ALF, ALS), RSA, prime d'activité, AAH, minimum vieillesse (Aspa et ASV), PAJE, ARS, ARE (y compris formation), pensions de retraite par régime, indemnités journalières : montant total, bénéficiaires et montant moyen par année depuis 2019, par département quand c'est publié. Agrégats publiés seulement. Commandes : `python pipeline/prestations.py collecter` (réseau ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/prestations.py produire` (sans réseau). Tests : `pytest tests/test_prestations.py`.

```
data/lake/secu/ (CNAF dep_tr_nat, s_ben_nat, s_ben_dep ; DREES comptes de la protection sociale et minima sociaux ;
                 Unédic ; France Travail allocataires indemnisés)
     └─> pipeline/prestations.py ─> site/data/prestations/index.json, nationales.json, departements/<annee>.json
                                      └─ liens (fichier + id) vers arbre/, secu/arbre/, secu/cps/, local/budgets/
```

| Champ | Sens |
|---|---|
| `sources_montant.<source>` | une série par source, jamais additionnée à une autre : `cnaf_depenses` (dépenses tous régimes, CAF et MSA), `drees_cps` (comptabilité nationale, détail par prestation depuis 2020), `unedic` ; `montant_eur` reprend la `serie_principale` |
| `beneficiaires` | foyers CAF payés en décembre (CNAF, champ CAF), allocataires au 31 décembre (DREES, Aspa) ou allocataires indemnisés fin décembre (France Travail, ARE) ; `beneficiaires_definition` le précise ; null pour les pensions et les indemnités journalières |
| `montant_moyen_eur` | par foyer et par mois (ARS : par an) ; `montant_moyen_methode` donne le calcul ; null quand effectifs et montants n'ont pas le même champ |
| `liens[]` (index) | `vue` (`arbre_etat`, `secu_arbre`, `secu_cps`, `local`), `fichier`, `id`, `md` (exécution 2024), `partage_avec` quand le nœud finance plusieurs prestations : même argent vu du côté du financeur, jamais additionné au montant de la prestation |
| `totaux.<source>` | somme des prestations couvertes dans une seule source (chaque code DREES compté une fois) ; `drees_cps` est rapproché du total de toutes les prestations de protection sociale |
| `ecarts[]`, `ecarts_departements[]` | `source`/`montant` contre `autre_source`/`autre_montant`, `ecart`, `ecart_pct`, `lecture_ecart` ; somme des départements (CAF) contre dépenses nationales tous régimes, `codes_mois_manquants` quand un mois manque à la source |
| départements | `colonnes` = `foyers_decembre`, `montant_annuel_eur`, `montant_moyen_eur` ; `financeur_rsa` = `departement`, `etat` (RSA recentralisé : 973 et 976 depuis 2019, 974 depuis 2020, 93 et 66 depuis 2022, 09 depuis décembre 2022) ou `departement_puis_etat` ; `hors_departements` : codes CNAF 978, 99, XX |

Règles propres : une valeur masquée ou absente à la source reste telle quelle (chaîne de la source ou null), jamais 0 ; une année incomplète à la source (Mayotte, décembre 2020 à 2024) a un montant annuel null. Non couverts par département : ARE, pensions, indemnités journalières (`couverture_departementale.non_couvert`, `sources_inaccessibles`).

### 2.26 Subventions par convention : `subventions/` (pipeline/subventions.py)

Subventions publiées au format des « données essentielles des conventions de subvention » (décret 2017-779, schéma SCDL `scdl/subventions` 2.1.2) ou dans un format voisin. Un lecteur par source ramène chaque ligne à un enregistrement commun (année, montant, SIREN, département, programme LOLF, dispositif) ; agrégats, règle des personnes morales et contrôles sont communs. Commandes : `python pipeline/subventions.py collecter` (réseau, par `collecte/collecte.py`, entrées `subv_*` de `collecte/catalogue.json`), `python pipeline/subventions.py produire` (sans réseau ; stock SIRENE des unités légales partagé avec `local.py`, `data/lake/_cache/local/`). Tests : `pytest tests/test_subventions.py`.

```
data/lake/_restreint/subventions/ (ADEME data-fair, Fonds vert, agence de l'eau Artois-Picardie, Culture 163 Mo lu en flux,
                                   festivals P131, ADSV, politique de la ville P147, FIR ARS Pays de la Loire)
data/lake/subventions/ (presse : classement des titres, dispositifs)      stock SIRENE (catégorie juridique)
     └─> pipeline/subventions.py ─> site/data/subventions/index.json, attribuants/<source>.json, annees.json,
                                    departements.json, beneficiaires.json, programmes.json (chacun < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `subventions/index.json` | `subventions_index` | `sources[]` (titre, attribuant, page, licence, millésime, `rattachement`, `additionne`, `inclus_dans`, années, conventions, `lignes_montant_non_communique`, `total_eur`, `nommes {nombre, montant_eur}`, `agrege_confidentialite {montant_eur, part_pct}`, `fichier`), `totaux` (sources additionnées), `recouvrements[]`, `limites`, `sources_inaccessibles[]`, `recherche_publique` (verdict, licence, date) |
| `subventions/attribuants/<source>.json` | `subventions_attribuant` | une source : `par_annee[]` (montant, conventions, montant nommé, lignes « nc »), `par_departement[]` (`departement` null = non publié), `par_dispositif[]` (50 premiers + `par_dispositif_autres`), `par_programme[]`, `beneficiaires` (groupe de bénéficiaires, 2.9 ; `top[]` ajoute `conventions` et, pour les équipes artistiques, `noms_usage`) ou `titres` (presse), `nommes`, `agrege_confidentialite`, `montant_retire_des_totaux_eur` |
| `subventions/annees.json` | `subventions_annees` | par année : `total_additionne_eur`, `par_source.<id>` (montant, conventions, lignes « nc ») |
| `subventions/departements.json` | `subventions_departements` | par département (codes de `local/geo`) : total additionné, `par_source`, `par_annee` ; `non_localise.<id>` |
| `subventions/beneficiaires.json` | `subventions_beneficiaires` | groupe de bénéficiaires toutes sources additionnées ; `top[].sources[]` |
| `subventions/programmes.json` | `subventions_programmes` | `programmes[]` (`programme`, `source`, `rattachement`, `additionne`, `par_annee[] {annee, montant_eur, montant_nomme_eur}`) ; `operateurs[]` (`source`, `operateur`, `programme_chef_de_file`, lien `fichier` + `id` vers `operateurs/operateurs.json`) |

**Rattachement LOLF** (`rattachement.type`) : `programme_source` (programme publié ligne par ligne : Culture, programmes 131, 175, 180, 224, 334, 361, 363) ; `programme_dispositif` (programme fixé par le dispositif : Fonds vert 380, et 113 pour les fichiers « p113 » ; politique de la ville 147 ; festivals et ADSV 131 ; presse 180) ; `operateur` (ADEME, chef de file 181 ; agences de l'eau, chef de file 113 : ressources propres de l'opérateur, aucun montant par programme) ; `hors_budget_etat` (FIR des ARS). **Usage prévu par `tracabilite.py`** (non branché) : pour un programme P et l'année N, `programmes[]` filtré sur `programme = P`, `additionne = true` et `annee = N` donne un montant engagé auprès de bénéficiaires identifiés (`montant_nomme_eur` : personnes morales nommées) ; il peut alimenter la part `beneficiaire_identifie` (2.14) avec `statut = approche` (montants engagés ou attribués, pas les paiements de l'exécution) et `subventions/attribuants/<source>.json` comme source, plafonné par la catégorie 61 à 64 du programme (`nature/<P>.json`) pour ne jamais dépasser la dépense d'intervention. Ne pas additionner une source `additionne = false` : elle détaille une autre source. Les `operateurs[]` se relient au nœud opérateur de `operateurs/operateurs.json` (même `id`), pas au programme.

**Règle personnes physiques (bloquante).** Seules les personnes morales sont nommées : catégorie juridique SIRENE `2xxx` à `9xxx` hors groupements de personnes physiques (`sirene.personne_morale`), lue dans le stock SIRENE. Agrégés dans `exclus_personnes_physiques_ou_non_identifies` : `dont_personnes_physiques_eur`, `dont_sans_siren_eur` (identifiant absent ou illisible : notation scientifique de la politique de la ville 2021, Fonds vert P113 2024, festivals sans SIRET), `dont_siren_introuvable_eur` (absent du stock), et pour les équipes artistiques (festivals, ADSV) `dont_nom_de_personne_possible_eur` (dénomination SIRENE retenue par le filtre de noms de `local.py`). `autres_non_verifies` est toujours vide (stock SIRENE complet). Colonnes jamais lues : adresse, parité ou genre, direction artistique (« qui dirige »), noms de dirigeants, objet de la convention. Les noms d'usage (festival, équipe) passent le même filtre. Presse : le bénéficiaire publié est un titre (publication) sans SIREN ; un titre est nommé s'il passe le filtre de noms, sinon agrégé dans `titres_non_nommes`. Fichiers sources en zone restreinte (`data/lake/_restreint/subventions/`), sauf presse.

**Règles propres.** Un montant vide ou « nc » n'est jamais compté 0 : la ligne va dans `lignes_montant_non_communique` et hors des sommes. Montants engagés ou attribués (pas payés), en euros. Deux sources qui se recouvrent ne sont jamais additionnées : festivals et ADSV sont inclus dans les données de la Culture (P131), la presse dans la Culture (P180) et les dispositifs de presse dans le classement par titre (`additionne = false`, `inclus_dans`) ; les lignes du Fonds vert instruites par l'ADEME sont retirées des totaux toutes sources (`montant_retire_des_totaux_eur`). Département : celui du bénéficiaire (ADEME, Culture, Fonds vert, festivals) ou du service attribuant (politique de la ville) ; non publié pour l'agence Artois-Picardie, les ADSV, le FIR et la presse. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

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
