# Contrat d'interface pipeline / site

Version du contrat : **1.0** (15/11/2026).

Ce document fixe ce que le pipeline (`pipeline/`) écrit dans `site/data/` et ce que le site lit, ainsi que le format d'entrée et de sortie du module de calcul personnel (exécuté dans le navigateur). Chaque format a son JSON Schema dans `docs/schemas/`. Le schéma fait foi en cas de doute ; ce document en donne le sens.

```
pipeline/transform.py ──> site/data/*.json ──> site (lecture)
                               │
                 docs/valider_contrat.py (docs/schemas/*.schema.json)

profil saisi ──> module de calcul (modele-social + publicodes) ──> résultat ou erreur
                                   └─> recoupement OpenFisca (optionnel) ─┘
```

Vérification : `python docs/valider_contrat.py` (installe `jsonschema` si absent). Code de sortie 1 si un fichier présent est non conforme ou si un fichier existant manque ; un fichier « prévu » absent est seulement signalé.

## 1. Règles communes

| Règle | Valeur |
|---|---|
| Encodage | UTF-8, JSON compact (sauf `meta.json`, indenté) |
| Chemins | relatifs à `site/data/` (ex. `"fichier": "arbre/Culture-et-medias_AQ_372.json"`) |
| Montants agrégés | milliards d'euros (`md`), nombres décimaux ; le champ `unite` du fichier le rappelle |
| Montants personnels | euros par an, positifs = montant prélevé ; le site affiche le mensuel = annuel / 12 |
| Années | chaînes `"2025"` dans les fichiers de données (clés JSON), entiers dans le module de calcul |
| Administrations | libellés exacts, sans accent : `Ensemble`, `Etat`, `Collectivites locales`, `Securite sociale` (secteurs S13, S1311, S1313, S1314 ; l'État inclut les organismes divers d'administration centrale) |
| Absence | `null` = donnée absente à la source, jamais 0 ; une clé absente = niveau non applicable |
| Évolution | ajout d'un champ facultatif : version mineure (1.1) ; renommage, suppression ou changement de type : version majeure (2.0) et mise à jour simultanée du site |

## 2. Fichiers de `site/data/`

| Fichier | Schéma | Contenu | Unité | Millésime actuel | Source | État |
|---|---|---|---|---|---|---|
| `meta.json` | `meta.schema.json` | provenance, date de génération, totaux de contrôle | divers | généré à chaque passage | pipeline | existant |
| `arbre/racine.json` + `arbre/<chemin>.json` | `arbre_etat.schema.json` | arbre du budget de l'État, profondeur libre | Md€ (CP) | PLF 2025 | data.economie.gouv.fr `plf25-depenses-2025-...` | existant |
| `sankey_etat.json` | `sankey_etat.schema.json` | flux État > grand poste > mission > programme | Md€ (CP) | PLF 2025 | idem | existant |
| `nature_etat.json` | `nature_etat.schema.json` | budget de l'État par titre et catégorie LOLF | Md€ (CP) | PLF 2025 | idem | existant |
| `programmes/<n>.json` | `programme.schema.json` | actions, sous-actions et nature d'un programme | Md€ (CP) | PLF 2025 | idem | existant |
| `arbre_administrations/racine.json` | `arbre_administrations.schema.json` | administration > fonction COFOG > sous-fonction | Md€ | 2024 | Eurostat `gov_10a_exp` | existant |
| `arbre_administrations/methode.json` | `arbre_administrations_methode.schema.json` | note de consolidation (transferts entre administrations) | Md€ | 2024 | Eurostat `gov_10a_exp`, `gov_10a_main` | existant |
| `administrations.json` | `administrations.schema.json` | recettes, dépenses, solde par administration | Md€ | 2005 à 2025 | Eurostat `gov_10a_main` | existant |
| `recettes.json` | `recettes.schema.json` | chaque impôt par administration bénéficiaire | Md€ | 2005 à 2025 | Eurostat `gov_10a_taxag` | existant |
| `cofog.json` | `cofog.schema.json` | dépenses publiques consolidées par fonction | Md€ | 2024 | Eurostat `gov_10a_exp` | existant |
| `deficit.json` | `deficit.schema.json` | solde public | Md€ (négatif = déficit) | 2023 à 2025 | Eurostat `gov_10dd_edpt1` | existant |
| `communes/<dep>.json` | `communes.schema.json` | taux TFB et TEOM par commune | % | exercice 2025 | data.economie.gouv.fr `fiscalite-locale-des-particuliers` | existant |
| `affectation_prelevements.json` | `affectation_prelevements.schema.json` | qui reçoit chaque prélèvement (ventilation de la CSG, etc.) | parts (0 à 1) | à créer (LFSS 2025) | LFSS, annexe « affectation des recettes » | **prévu** |

Le millésime réel est toujours lu dans le fichier (`annee`, `annees`, clés d'année) ou dans `meta.json` (`controle.exercice`, `controle.annee_cofog`, `controle.administrations_derniere_annee`, `controle.recettes_annees`, `controle.arbre_administrations.annee`) : le site ne code aucune année en dur.

### 2.1 `meta.json`

| Champ | Type | Sens |
|---|---|---|
| `genere_le` | chaîne date-heure ISO 8601 | fin du passage du pipeline |
| `sources.<jeu>.source` | chaîne | identifiant de la source (portail/jeu) |
| `sources.<jeu>.maj_source` | chaîne ISO 8601 ou `null` | date de mise à jour déclarée par la source |
| `controle.total_md` | nombre > 0 | total du budget de l'État retenu (hors remboursements et dégrèvements) |
| `controle.exclu_remboursements_md` | nombre | montant exclu (restitutions d'impôts) |
| `controle.exercice` | `"AAAA"` | exercice des taux communaux |
| `controle.communes`, `controle.departements` | entiers | nombre de communes (≥ 30 000) et de départements (≥ 96) |
| `controle.annee_cofog`, `controle.administrations_derniere_annee`, `controle.tva_annee` | `"AAAA"` | millésimes Eurostat |
| `controle.recettes_annees` | `"AAAA-AAAA"` | plage de `recettes.json` |
| `controle.deficit_derniere_annee` | `["AAAA", nombre]` | dernier solde public |
| `controle.tva_derniere_annee` | objet administration → Md€ | TVA par bénéficiaire |
| `controle.arbre`, `controle.arbre_administrations` | `{noeuds, feuilles, profondeur, fichiers}` (+ `annee`, `somme_md`, ...) | statistiques des arbres |
| `version_contrat` | `"1.0"` | **prévu** : à écrire par le pipeline ; le site refuse une version majeure différente |

### 2.2 Arbres (`arbre/*.json`, `arbre_administrations/racine.json`)

Un nœud : `{"id", "nom", "niveau", "md", "enfants"?, "fichier"?, "nb_enfants"?}`.

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | chemin des clés depuis la racine, séparées par `/` (ex. `Education et recherche/EC/141`) ; `racine` pour la racine |
| `nom` | chaîne | libellé affichable |
| `niveau` | énuméré | État : `racine`, `grand_poste`, `mission`, `programme`, `action`, `sous_action`, `titre`, `categorie` (ordre fixé par `pipeline/niveaux.json`) ; administrations : `racine`, `administration`, `fonction`, `sous_fonction` |
| `md` | nombre ≥ 0, 6 décimales | montant du nœud = somme de ses enfants |
| `enfants` | tableau non vide de nœuds | triés par montant décroissant ; absent sur une feuille |
| `fichier` + `nb_enfants` | chaîne + entier | point de découpe (après `programme`) : sous-arbre à charger à la demande ; exclusif de `enfants` |

Un niveau non renseigné par la source est sauté (branche moins profonde). Le validateur contrôle aussi que chaque `fichier` référencé existe. Dans l'arbre des administrations, la sous-fonction GF0108 (transferts entre administrations) est retirée ; la somme des administrations (1 732,7 Md€ en 2024) dépasse donc le total consolidé (1 671,8 Md€), expliqué par `methode.json`.

### 2.3 `sankey_etat.json`

`{"unite", "total", "nodes": [{"id", "name", "level"}], "links": [{"source", "target", "value"}]}`. `id` préfixé : `etat`, `p:<grand poste>`, `m:<mission>`, `g:<numéro de programme>` ; `level` 0 à 3 ; `source`/`target` = index dans `nodes` ; `value` en Md€ > 0. Conservation : à chaque niveau, la somme des liens sortants égale `total`.

### 2.4 `nature_etat.json` et `programmes/<n>.json`

`nature_etat.json` : `titres[]` de `{titre: "1".."7", nom, md, categories: [{code: "NN", nom, md}]}`.
`programmes/<n>.json` : `{programme: entier 100..999, actions: [{code, nom, md, sous_actions: [{code|null, nom|null, md}]}], nature: {libellé de catégorie: md}}`. `code`/`nom` de sous-action à `null` quand la source n'a pas de sous-action.

### 2.5 `administrations.json`

`annees.<AAAA>.<administration>.<agrégat>` = Md€. Agrégats : `TR` recettes, `TE` dépenses, `B9` solde, `D73PAY` transferts courants versés à d'autres administrations, `D92PAY` aides à l'investissement versées, `D99PAY` autres transferts en capital versés. Les quatre administrations sont présentes chaque année.

### 2.6 `recettes.json`

`{unite, annees: ["2005", ...], impots: {<code SEC>: {nom, par_administration: {<administration>: {<AAAA>: md}}}}}`. Codes présents : `D2`, `D211` (TVA), `D214A`, `D29`, `D5`, `D51A_C1` (impôt sur le revenu des ménages), `D51B`, `D61` (cotisations sociales), `D91`. `D211`, `D51A_C1` et `D61` sont obligatoires (utilisés par le calcul personnel). Une année absente pour une administration = pas de recette déclarée.

### 2.7 `cofog.json` et `deficit.json`

`cofog.json` : `{annee, unite, fonctions: [10 × {code: "GF01".."GF10", nom, md}], total}`.
`deficit.json` : `{unite, solde_public: {<AAAA>: md}}`, négatif = déficit.

### 2.8 `communes/<dep>.json`

Un fichier par département (`01` à `95`, `2A`, `2B`, `971` à `976`), objet `{<code INSEE>: [nom, taux_tfb, taux_teom]}` :

| Position | Type | Sens |
|---|---|---|
| 0 | chaîne | nom DGFiP (majuscules, sans accent) |
| 1 | nombre ou `null` | taux global de taxe foncière sur le bâti, en % (somme commune, EPCI et taxes annexes ; peut dépasser 100) |
| 2 | nombre ou `null` | taux plein de TEOM en % ; `null` = pas de TEOM (déchets financés par la REOM ou le budget général) |

Le département se déduit du code INSEE : 2 premiers caractères en métropole et Corse, 3 en outre-mer (`97411` → `974.json`).

### 2.9 `affectation_prelevements.json` (prévu)

`{annee, source, destinataires: {<id>: {nom, administration, url?}}, prelevements: {<id prélèvement>: {libelle?, ventilation: [{destinataire, part}], reference_juridique?}}}`. La somme des `part` d'un prélèvement vaut 1. Tant que ce fichier est absent, les prélèvements partagés (CSG) ont le destinataire `plusieurs` et un avertissement `DONNEE_ABSENTE`.

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
