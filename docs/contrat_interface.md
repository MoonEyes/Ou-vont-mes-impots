# Contrat d'interface pipeline / site

Version du contrat : **1.6** (17/11/2026).

| Version | Date | Changement |
|---|---|---|
| 1.0 | 15/11/2026 | fichiers budget de l'État, Eurostat, communes ; module de calcul personnel |
| 1.1 | 15/11/2026 | précision par programme : `nature/`, `effectifs/`, `beneficiaires/` |
| 1.2 | 16/11/2026 | bloc « Ce qui a été fait » : `realisations/` |
| 1.3 | 17/11/2026 | `vie_politique/` ; schémas 1.0 alignés sur les fichiers réellement produits (en-tête `millesime`/`source`, enveloppe `communes`, `deficit.json` État et APU, nœuds `psr:` du sankey, montants d'exécution négatifs, arbres LFI 2025 et nature PLF 2025) |
| 1.4 | 17/11/2026 | `prelevements/` : affectation sourcée de chaque prélèvement, taxes sur la consommation par décile, taxe foncière estimée par commune |
| 1.5 | 17/11/2026 | `secu/` : arbres Sécurité sociale et protection sociale (comptes des organismes, exécution 2024 et 2025 ; prestations DREES 2024), source, millésime et taux de traçabilité par nœud, écarts entre sources |
| 1.6 | 17/11/2026 | `mise_a_jour.json` : rapport du dernier passage de la mise à jour automatique (`pipeline/tout.py`), statut de chaque étape et sources inaccessibles |

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
| `eur_sur_100` | montant / total de l'arbre État (`arbre/racine.json`, exécution 2024) × 100, à lire « X € sur 100 € du budget de l'État ». Exception : `vie_politique/annees.json` rapporte ses montants au budget général hors remboursements et dégrèvements (`denominateur` publié dans le fichier, libellé « budget général »), pas à l'arbre |
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
| `mise_a_jour.json` | `mise_a_jour.schema.json` | statut de chaque étape du dernier passage, sources inaccessibles | | généré à chaque passage | `tout.py` | existant |
| `arbre/racine.json` + `arbre/<chemin>.json` | `arbre_etat.schema.json` | arbre du budget de l'État (vue par défaut) | Md€ (CP) | Exécution 2024 | `transform.py` (budget vert PLF 2026 + PLRG 2024) | existant |
| `arbre_lfi2025/` | `arbre_etat.schema.json` | même arbre, crédits votés | Md€ (CP) | LFI 2025 | `transform.py` | existant |
| `arbre_plf2025_nature/` | `arbre_etat.schema.json` | vue séparée par nature (sous-action, titre, catégorie) | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `sankey_etat.json`, `sankey_etat_lfi2025.json` | `sankey_etat.schema.json` | flux État > grand poste > mission > programme | Md€ (CP) | Exécution 2024, LFI 2025 | `transform.py` | existant |
| `nature_etat.json` | `nature_etat.schema.json` | budget de l'État par titre et catégorie LOLF | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `programmes/<n>.json` | `programme.schema.json` | actions, sous-actions et nature d'un programme | Md€ (CP) | PLF 2025 | `transform.py` | existant |
| `arbre_administrations/racine.json` | `arbre_administrations.schema.json` | administration > fonction COFOG > sous-fonction | Md€ | 2024 | `transform.py` (Eurostat `gov_10a_exp`) | existant |
| `arbre_administrations/methode.json` | `arbre_administrations_methode.schema.json` | note de consolidation : `ecart_consolidation_md` = `somme_administrations_md` - `total_consolide_md` ; `ecart_depenses_totales_md` (TE, `gov_10a_main`) et `ecart_tables_eurostat_md` publiés à part, avec `definitions` | Md€ | 2024 | idem | existant |
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
| `territoires/index.json`, `territoires/<dep>.json` | `territoires_index.schema.json`, `territoires_departement.schema.json` | projets DETR/DSIL/DPV/DSID par bénéficiaire, inventaire SRU par commune, aide sociale départementale (DREES) par poste, écarts entre sources | €, € par habitant, % | projets 2018-2025, SRU 2023-2026, aide sociale 1999-2024 | `territoires.py` | existant |
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
| `associations/index.json`, `associations/programmes/<p>.json`, `associations/fonds_fondations.json`, `associations/reserve/<an\|senat>_<annee>.json` | `associations_*.schema.json` | crédits de l'État par association et par programme (jaunes PLF 2012 à 2025), fonds et fondations (RNF), réserve parlementaire par parlementaire (bénéficiaires personnes morales nommés, le reste agrégé) | € | PLF 2012-2025 (crédits 2010-2023, PLF 2024 « nc ») ; RNF 01/11/2026 ; réserve AN 2013-2016, Sénat 2014-2017 | `associations.py` | existant |
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
| `beneficiaire_identifie` | bénéficiaire nommé par une source publique (associations, marchés de l'État, France 2030, partis et remboursements de campagne, bénéficiaire unique désigné par le programme, Union européenne, subventions pour charges de service public 2024 aux opérateurs d'après le jaune « Opérateurs de l'État », réparties entre programmes financeurs par ajustement proportionnel ; plafond par programme = part de la catégorie 32 dans `nature/<n>.json` × montant du programme dans l'arbre, et non la catégorie 32 du PLRG, que l'arbre retraité peut dépasser, voir 2.21) ou catégorie fixée par la loi (collectivités : prélèvements, dotations 119 et 122) ; `niveau_identification` = `entite` ou `categorie` |
| `nominatif_par_choix` | titre 2 : la catégorie d'agents est publiée, pas les noms |
| `anonyme_par_nature` | charge et amortissement de la dette (catégories 41 à 43, programme 369) |
| `non_publie` | le reste ; un programme net négatif y est rangé en entier |

Une part porte `{libelle, eur, pct, statut, ecart_millesime_ans, sources[]}` ; `statut` = `exact` (numérateur et dénominateur de la même année) ou `approche` (avec l'écart de millésime et `raison_approche` dans `composantes`) ; une part non nulle a au moins une source. `maillons[]` donne des couvertures indépendantes : `programme` (100), `nature`, `destinataire` (= `taux_tracabilite_pct`), `beneficiaire_nomme`.

**Décisions.** `decisions/programme_<n>.json` : `annees.<AAAA>` (LFI, LFR, reports, mouvements réglementaires, fonds de concours, ouverts et dépenses du PLRG 2023 à 2025 ; comptes d'amendements ; `amendements_adoptes[]` ; `mouvements_jo[]`) et `chronologie[]` triée. Un montant du PLRG que le pipeline ne sait pas lire est `null` avec sa raison (`valeurs_illisibles_plrg`, `raison` dans la chronologie), jamais 0 ; un montant publié en notation scientifique par la source est lu et signalé (`precision_plrg`, `precision`). Contrôle bloquant de `produire` et de `plrg` (régénération ciblée des seuls champs du PLRG) : LFI, crédits ouverts et dépenses égaux à `realisations/<n>.json` à 1 € près. `amendements_resume.json` : amendements de crédits déposés et adoptés (séance, commission) et montant net par programme et par année, Assemblée et Sénat, 17e législature. `scrutins.json` : scrutins publics de l'Assemblée sur les lois de finances (ensemble, parties, articles, crédits, amendements de crédits). `mouvements_<AAAA>.json` (2021 à 2026) : décrets et arrêtés de mouvements de crédits (avance, annulation, virement, transfert, répartition, report, fonds de concours) avec leurs lignes par programme, montants signés (ouverture > 0). `coherence_plrg.json` : somme des lignes JO par colonne du PLRG (mouvements réglementaires, reports, fonds de concours), écart publié et `conforme` d'après la tolérance publiée (1 % par an, 1 000 € par programme). `index.json` : programmes, fichiers, comptes, limites.

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
| `local/dotations/communes/<dep>.json`, `epci.json`, `departements.json`, `regions.json` | `local_dotations_*` | DGF et composantes (communes : `dgf_commune_nouvelle` publiée à part, hors `dgf_totale` ; EPCI : `dgf_ecart_composantes` quand le total notifié diffère de ses deux composantes), DCRTP, DILICO ; DETR/DSIL/DPV/DSID par projet | DGCL via OFGL, data.gouv |
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

**`secu/index.json`** : `vue_defaut`, `vues.<vue>` (`millesime`, `fichier`, `total_md`, `noeuds`, `feuilles`, `profondeur`, `fichiers`, `tracabilite_pct`, `modes_md`), `liens_affectation` (`noeuds` : destinataire → nœud ; `sans_noeud` : destinataires Sécurité sociale de `prelevements/affectation.json` sans nœud propre, avec `motif` et `noeud_englobant`), `verification_documents` (chaque document : `vérifié` ou absent ; la production échoue si un montant saisi n'est plus dans le document), `sources`, `sources_inaccessibles[]` (`{source, motif}`), `recherche_publique` (`trouvailles[]` : verdict `réutilisable tel quel`, `à adapter` ou `inspiration seulement`, licence, date du dernier commit ou de mise à jour).

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

**`niches/programmes.json`** : `programmes[]` (`programme`, `noeud`, `nom`, `mission`, `grand_poste`, `mesures[]`, `fiscal_meur.<2024|2025|2026>` (`null` quand aucune mesure du programme n'est chiffrée et qu'une au moins est « nc » ou « ε » : la raison est dans `mention.<année>`, jamais 0 ; les coûts `hors_reference` restent hors de cette somme et sont publiés dans `hors_reference_meur`), `non_chiffrees.<année>`, `budget_meur` = exécution 2024 de l'arbre, `total_2024_meur`, `part_fiscale_2024`), `missions[]` et `grands_postes[]` (mêmes sommes ; `budget_meur` = programmes porteurs de mesures seulement, `budget_arbre_meur` = tous les programmes de la mission ou du grand poste dans l'arbre, `programmes_non_chiffres.<année>`), `hors_arbre[]` (programme absent de l'arbre), `couverture` (part du coût 2024 rattachée à un programme de l'arbre). Dépense fiscale (perte de recettes estimée) et dépense budgétaire (décaissement) s'additionnent pour lire l'effort par politique, sans se confondre.

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

**Part de 100 € d'impôt qui paie des intérêts** (`interets.json` → `cas_type`) : cas C04 (2 100 € net, célibataire, locataire). Répartition par administration de ce que paie le foyer calculée avec le module du site appelé comme l'écran résultat (`web/src/ecrans/saisie.ts` : `calculer`, `assembler`, `parAdministration`), sur le périmètre de la carte : prélevé sur salaire et IR, taxes sur la consommation centrales, TEOM de la commune. Variante principale : locataire à Lyon (69123), 13 891,94 € par an comme la carte ; `variantes` publie aussi Nantes (variante de comparaison, pas la commune du cas type) et « sans commune » (TEOM non chiffrée, 0 €), seule différence entre elles ; chaque part est multipliée par la part des intérêts dans les dépenses de l'administration qui la reçoit (comptabilité nationale, dernière année). `lecture_budgetaire_etat` donne à part la place du programme 117 dans l'arbre État : les deux lectures ne s'additionnent pas.

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

### 2.22 Rapport de mise à jour : `mise_a_jour.json` (pipeline/tout.py)

Producteur : `pipeline/tout.py` (orchestrateur du workflow hebdomadaire `.github/workflows/data.yml`), à la fin de chaque passage. Déterministe hors `genere_le` : ni durée ni code de sortie (le journal détaillé, avec les durées, est `data/lake/_cache/tout/journal.json`, non versionné, et le résumé du job GitHub). Comme `genere_le` de `meta.json`, ce fichier **ne déclenche jamais de commit à lui seul** ; il est committé avec les données quand une donnée change.

| Champ | Type | Sens |
|---|---|---|
| `millesime`, `source` | chaînes | en-tête commun |
| `genere_le` | date-heure ISO 8601 | fin du passage |
| `mode` | `complet` ou `sans réseau` | `sans réseau` : commandes de collecte non lancées |
| `statuts` | objet statut → définition | lexique des statuts ci-dessous |
| `etapes[]` | `{etape, titre, dependances[], sorties[], statut, motif, sources_inaccessibles[]}` | une entrée par étape, dans l'ordre des dépendances ; `sorties` relatives à `site/data/` |
| `etapes[].statut` | `produit`, `partiel`, `conserve`, `echec`, `reporte` | `produit` : sorties régénérées ; `partiel` : passage reprenable non terminé (`local.py`), sorties déjà produites gardées ; `conserve` : entrée absente de l'entrepôt ou source inaccessible pendant la production, **dernière version publiée gardée** ; `echec` : erreur de code ou de donnée, dernière version publiée gardée et passage en erreur ; `reporte` : budget de temps épuisé |
| `etapes[].sources_inaccessibles[]` | `{commande, constat}` | refus ou indisponibilité (401, 403, 429, 5xx, délai, coupure) constatés pendant la collecte : la production a tourné sur le cache, rien n'a été contourné |

Une étape absente du passage (`--etapes`) garde sa ligne du passage précédent.

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

### 2.25 Territoires : `territoires/` (pipeline/territoires.py)

Complète « Près de chez moi » (2.15) par département : chaque projet financé par les dotations de soutien à l'investissement local (DETR, DSIL, DPV, DSID, programme 119, exercices 2018 à 2025), l'inventaire SRU par commune (éditions 2023 à 2026) et l'aide sociale départementale de la DREES (1999 à 2024). Commandes : `python pipeline/territoires.py collecter` (réseau, par `collecte/collecte.py` ; sources déclarées dans `collecte/catalogue.json`), `python pipeline/territoires.py produire [--sortie DOSSIER]` (sans réseau ; lit `site/data/local/` en lecture seule). Tests : `pytest tests/test_territoires.py`.

```
data/lake/collectivites/ (DGCL projets 2018-2025 ; inventaire SRU ; DREES 376 séries longues, APA et PCH)
data/lake/secu/drees__619_indicateurs-financiers.parquet (ISD)      site/data/local/ (geo, population OFGL, dotations)
     └─> pipeline/territoires.py ─> site/data/territoires/index.json, <dep>.json (un par département de local/geo, < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `territoires/index.json` | `territoires_index` | couverture par source, totaux (projets par exercice et dispositif ; totaux estimés de la DREES), écarts nationaux, contrôle croisé avec `local/dotations/communes`, postes et mesures, méthode, limites, sources (verdict, licence, date de collecte), sources inaccessibles, recherche préalable |
| `territoires/<dep>.json` | `territoires_departement` | `investissement_etat` (bénéficiaires, projets `[exercice, dispositif, intitule, cout_ht_eur, subvention_eur, taux]`, totaux, `par_commune`, non nommés agrégés, anomalies publiées), `sru` (par commune et édition), `aide_sociale` (par collectivité : postes brut/net en euros et euros par habitant, ISD, APA à domicile, PCH), `ecarts`, `liens` vers `local/` |

Jointure : communes par code INSEE (mêmes clés que `local/geo/<dep>.json`), intercommunalités et autres bénéficiaires par SIREN, départements par le code de `local/geo`. `par_commune.<insee>` donne les bénéficiaires qui concernent la commune (elle-même, son EPCI) et le fichier où les lire. Alsace et Corse : la collectivité unique (`6AE`, `20R`) figure dans les fichiers des deux départements avec son `perimetre`, à ne pas additionner ; Rhône : `69` (territoire), `69D`, `69M`.

DETR/DSIL/DPV/DSID par projet (annoncés en 2.15) : la source est le jeu DGCL déclaré dans `collecte/catalogue.json` ; `local/dotations/communes` garde les 15 projets les plus élevés par commune et par exercice, la liste complète est ici et ses totaux sont comparés à ceux de `local/` (`controle_local`).

Règles propres : une valeur absente ou masquée à la source (vide, « ND », « NR », « NA », « Pas d'inventaire », « >25% ») reste null, la marque est gardée (`marque_source`, `taux_sru_texte`, `lls_texte`), jamais 0 ; un 0 publié reste 0 (allocation du RSA recentralisé) ; « - € » dans la colonne du prélèvement SRU (format comptable) vaut 0 € et la chaîne publiée est gardée dans `prelevement_texte`. Bénéficiaire nommé seulement s'il est une commune ou une intercommunalité du COG, un département, une collectivité d'un type public publié par la DGCL ou une personne morale SIRENE (catégorie 2xxx à 9xxx) ; le reste est agrégé sans nom ni intitulé (`exclus_personnes_physiques_ou_non_identifies`) ; intitulé null s'il peut contenir un nom de personne (règle de `local.py`). Deux sources ne sont jamais additionnées : `ecarts[]` publie `source`/`montant` contre `autre_source`/`autre_montant`, `ecart`, `ecart_pct`, `lecture` (euros par habitant calculés contre ISD ; APA à domicile brute contre dépenses couvertes ; somme des collectivités contre total estimé de la DREES). Ordre écrit dans `ordre`. Dates par `pipeline/reproductible.py`.

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

### 2.27 Associations, fonds et fondations, réserve parlementaire : `associations/` (pipeline/associations.py)

Producteur : `pipeline/associations.py`. Sources déclarées dans `collecte/catalogue.json` (`assoc_jaune_plf2012` à `assoc_jaune_plf2024`, `assoc_rnf_fonds_fondations`, `assoc_reserve_an`, `assoc_reserve_senat` en zone restreinte car elles contiennent des adresses, `assoc_banatic_siren_insee`, `assoc_departements`) ; jaune PLF 2025 lu par `pipeline/beneficiaires.py` ; stock SIRENE des unités légales partagé avec `pipeline/local.py`. Commandes : `python pipeline/associations.py sirene` (extrait SIRENE en cache), `python pipeline/associations.py apparier --budget 600` (réseau, reprenable : API Recherche d'entreprises, un refus 401/403 arrête sans contournement), `python pipeline/associations.py produire [--sortie DOSSIER]` (sans réseau, reproductible). Tests : `pytest tests/test_associations.py`.

```
data/lake/associations/ (jaunes PLF 2012-2024, RNF, Banatic, départements)   data/lake/beneficiaires/ (jaune PLF 2025)
data/lake/_restreint/associations/ (réserve AN 2013-2016, Sénat 2014-2017)   stock SIRENE (catégorie juridique, RNA)
     └─> pipeline/associations.py ─> site/data/associations/index.json, programmes/<p>[_<k>].json,
                                     fonds_fondations.json, reserve/<an|senat>_<annee>.json (chacun < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `associations/index.json` | `associations_index` | `annees[]` (année du PLF, `annee_credits` = année de versement, `statut` `publie` ou `nc`, totaux publiés, nommés, exclus, non vérifiés, `associations_nommees`, `jeu_datagouv`, `correction` le cas échéant), `programmes[]` (`fichiers[]`, `totaux_eur[]` alignés sur les années), `fonds_fondations`, `reserve[]` (totaux, part agrégée), `sources_inaccessibles[]`, `recherche_publique` |
| `associations/programmes/<p>.json` | `associations_programme` | un programme LOLF tel que publié chaque année (`sans_programme` : PLF 2012 sans imputation) : `colonnes` = `siren`, `denomination`, `categorie_juridique`, `total_eur`, `montants_eur[]` (alignés sur `annees`), `par_annee[]` (total publié, nommés, exclus, non vérifiés : conservation à 1 € près), `ordre` ; découpé en `<p>_1.json`, `<p>_2.json` au-delà de 4,8 Mo (`partie`, `parties`) |
| `associations/fonds_fondations.json` | `associations_fonds_fondations` | RNF : numéro, titre, type (FDD, FE, FRUP), objet social filtré (≤ 400 caractères), date de création, domaine, état, préfecture, SIRET, catégorie juridique, années de subventions publiques déclarées (le registre ne publie pas de montant), années d'appel à la générosité publique |
| `associations/reserve/<an\|senat>_<annee>.json` | `associations_reserve` | par parlementaire (nom, groupe, département, total) : `beneficiaires_nommes[]` (`siren`, `denomination`, `categorie_juridique`, `rna`, `programme`, `montant_eur`, `descriptif` filtré, `methode_appariement`) et `agreges` ; totaux, `part_agregee_pct`, `par_programme[]`, `appariements` |

**Valeurs.** Un montant de la série est un nombre (montant publié), `null` (association absente de la liste de l'année pour ce programme) ou `"nc"` (liste de l'année non publiée ou inexploitable : PLF 2024, dont le jeu publié ne contient qu'une colonne de nombres) : jamais 0 à la place d'une absence. PLF 2013 : l'export publié multiplie chaque montant par 10 (tous les montants sont des multiples de 10, rapport médian de 10 avec les mêmes couples association × programme des PLF 2012 et 2014) ; montants divisés par 10, preuve recalculée à chaque production dans `annees[].correction` (arrêt si elle ne tient plus). PLF 2012 : la ligne « Total des subventions versées en 2010 » sert de contrôle (`total_publie_par_la_source_eur`, égal à la somme des lignes à 1 € près, sinon arrêt) et n'est pas comptée. Les jaunes ne sont pas homogènes d'une année à l'autre (périmètre, programmes renumérotés) : la série juxtapose les montants publiés.

**Règle personnes physiques (bloquante).** Seules les personnes morales sont nommées (catégorie juridique `2xxx` à `9xxx` hors groupements de personnes physiques, lue dans la source ou le stock SIRENE). Entrepreneurs individuels, SIREN invalides, bénéficiaires de la réserve non appariés : agrégés, jamais nommés. Aucune adresse, code postal ni ville d'organisme n'est publié (colonnes d'adresse de la réserve et du RNF jamais lues). Textes libres (objet social du RNF, descriptif de la réserve) : filtre de noms de `pipeline/local.py` (civilité, prénom fréquent suivi d'un nom) et d'adresses (numéro suivi d'un type de voie), `null` en cas de doute.

**Réserve parlementaire.** Les parlementaires sont nommés dans leur rôle public (listes publiées par l'Assemblée et le Sénat), comme les élus et candidats de 2.11 : nom tel que publié, groupe, département. Appariement d'un bénéficiaire à une personne morale : commune du département du parlementaire (table SIREN / Insee de la DGCL, nom identique, homonymes du département écartés) ; sinon même programme et même montant dans le jaune associations de la même année avec un nom proche (indice de Jaccard ≥ 0,5, candidat unique) ; sinon API Recherche d'entreprises (nom identique ou indice ≥ 0,75 dans le département, candidat unique, catégorie juridique 7xxx à 9xxx : organismes publics, associations, fondations). RNA repris du stock SIRENE. **Ordre neutre** écrit dans `ordre` : parlementaires par `nom_tri` (nom puis prénom, capitales sans accents), bénéficiaires par montant décroissant puis dénomination ; aucun total par groupe politique. Un parlementaire par ailleurs candidat à un scrutin national (présidentielle, tête de liste européenne) n'est pas nommé : la règle 2.11 ne nomme ces candidats que dans `vie_politique/candidats/` ; ses attributions sont comptées dans `parlementaires_non_nommes` et `agreges.parlementaires_non_nommes_eur`. Une association de financement ou mandataire de campagne électorale, ou toute dénomination portant le nom d'un tel candidat, n'est jamais nommée (`dont_denomination_nominative_eur`).

### 2.28 Numérique de l'État : `numerique_etat/` (pipeline/numerique_etat.py)

Producteur : `pipeline/numerique_etat.py`. Sources déclarées dans `collecte/catalogue.json` (`numerique_*`, domaine `numerique_etat`, data.gouv.fr, Licence Ouverte 2.0) et collectées par `python collecte/collecte.py numerique_panorama_projets numerique_france_relance_mtfp numerique_ftap_guichets numerique_fast numerique_ditp_guichets` (réseau) ; `python pipeline/numerique_etat.py produire [--sortie DOSSIER]` (sans réseau). Tests : `pytest tests/test_numerique_etat.py`. Chaque fichier porte `millesime`, `source`, `unite`, `collecte_le`.

```
panorama des grands projets numériques (DINUM, 22 classeurs) ─┐
France Relance numérique (MTFP), guichets DITP, FTAP, FAST ───┼─> pipeline/numerique_etat.py ─> site/data/numerique_etat/
arbre État (site/data/arbre, programmes et actions) ──────────┘
```

| Fichier | Contenu |
|---|---|
| `numerique_etat/index.json` | `sources[]` (jeu, producteur, licence, date de la ressource, date de collecte), `panorama` (synthèse et liens `fichiers`), `fonds[]` (`id`, `fichier`, totaux, `arbre_etat`), `annees.fichier`, `recherche_publique.trouvailles[]` (verdict, licence, date) |
| `numerique_etat/panorama/projets.json` | par projet : `id`, `nom` (dernier nom publié), `noms_publies[]`, `ministere` (sigle publié), `editions` (nombre, première, dernière, `dans_la_derniere_edition`), `debuts_publies[]`, `evolution_cout_meur` et `evolution_duree_ans` (première et dernière valeur publiées, `ecart`, `ecart_pct`, `minimum`, `maximum` ; null si moins de deux valeurs publiées), `programmes[]`, `releves[]` (une ligne par édition : `cout_meur`, `cout_mention`, `duree_ans`, `duree_mention`, `debut` AAAA-MM, `phase`, `tranche`, `programmes`) ; `methode.regles[]`, `rapprochements[]`, `non_rapproches[]` |
| `numerique_etat/panorama/editions.json` | par édition (`edition` AAAA-MM, `numero`, `annee`, `url` du classeur) : `projets`, `cout_publie_meur`, `projets_sans_cout_publie`, `entrants[]`, `sortants[]`, `par_tranche`, `par_ministere[]` ; `annees[]` (éditions parues chaque année) |
| `numerique_etat/panorama/ministeres.json` | par sigle de ministère porteur tel que publié : `noms_publies[]`, série par édition (`projets`, `cout_publie_meur`, `projets_sans_cout_publie`, `projets_ids[]`) |
| `numerique_etat/panorama/programmes.json` | par programme LOLF cité dans « Financement [programme(s)] » : `programme`, `dans_arbre`, `noeud` et `fichier` de l'arbre État (null si le programme n'est pas dans l'arbre de l'exécution 2024), `projets[]` (dernier coût estimé publié, programmes cités ensemble) ; `projets_sans_programme_relie[]` |
| `numerique_etat/fonds/france_relance.json` | France Relance, mise à niveau numérique de l'État et des territoires : `total`, `par_dispositif[]`, `par_ministere[]`, `par_annee[]` (année de décision), `departements[]` (`code`, `nom`, totaux, `fichier`), `arbre_etat`, `confidentialite` |
| `numerique_etat/fonds/france_relance/<dep>.json` | projets du département : `dispositif`, `libelle_dispositif`, `ministere`, `porteur`, `titre`, `montant_eur`, `date_decision` |
| `numerique_etat/fonds/ditp.json` | guichets DITP : `fitn8` (projets nationaux : `ministere`, `porteur`, `cout_total_projet_eur`, `montant_eur`, par ministère et par année) et `itn7_volet1` (fonds déconcentré : `par_type`, `par_region`, `departements[]`) |
| `numerique_etat/fonds/ditp_itn7/<dep>.json` | projets de collectivités du département : `collectivite`, `code_insee`, `projet`, `type`, `cout_total_projet_eur`, `montant_eur` |
| `numerique_etat/fonds/ftap.json` | lauréats des guichets numériques du FTAP : `guichet`, `projet`, `incubateur`, `ministere`, `porteur`, `montant_eur` ; `par_guichet[]`, `par_ministere[]` ; `par_annee` null (date de convention non publiée) |
| `numerique_etat/fonds/fast.json` | lauréats du FAST : `appel`, `annee`, `laureat`, `projet`, `objet`, `montant_eur`, `dont_coaching_eur` ; `par_appel[]`, `par_annee[]` |
| `numerique_etat/annees.json` | par année : éditions du panorama, décisions France Relance et FITN8, appels FAST, chacun dans sa colonne |

**Unités.** Panorama : millions d'euros (`*_meur`, coût estimé publié par la DINUM) et années ; fonds : euros (`*_eur`). `null` = valeur absente à la source (« en cadrage », non communiqué, cellule vide), jamais 0 ; la raison est dans `cout_mention` et `duree_mention`. Les totaux n'additionnent que les valeurs publiées et donnent à côté le nombre de lignes sans valeur.

**Évolution du coût estimé publié.** Les valeurs sont celles que chaque édition publie ; un écart entre deux éditions peut venir d'un changement de périmètre, de calendrier ou de méthode, que la source ne précise pas. Rapprochement des noms d'une édition à l'autre : R1, même nom une fois normalisé (majuscules, accents, ponctuation) ; R2, changement de nom déclaré dans le code (`RENOMMAGES`), appliqué seulement si aucune édition ne contient les deux noms, si la date de début publiée est la même à la jonction et, quand le nom ajoute ou retire une mention de version, de cycle, de phase ou de périmètre, si le coût estimé publié y est le même à 0,1 M€ près ; R3, un changement déclaré dont un critère échoue reste non rapproché (deux projets), avec la raison dans `non_rapproches`. La production échoue si un même nom figure deux fois dans une édition.

**Lien avec l'arbre État.** Panorama : numéros de programme lus dans la colonne « Financement [programme(s)] », à défaut intitulé strictement identique à un programme de l'arbre ; un projet financé par plusieurs programmes figure sous chacun avec son coût entier, sans répartition ni somme entre programmes. Fonds : `arbre_etat` désigne l'action de l'arbre dont l'intitulé nomme le dispositif (363-04 pour France Relance numérique et la DITP, 349-01 pour le FTAP, 352-01 pour le FAST) ; la production échoue si l'action n'existe plus sous cet intitulé.

**Confidentialité.** Les jeux ne publient aucun SIREN ; les porteurs sont des administrations, des établissements publics et des collectivités. Un nom de porteur ou un titre où un nom de personne ou une coordonnée est possible (filtre de `pipeline/local.py`, courriel, téléphone, lien) est remplacé par `null`, le montant reste publié et le nombre de cas est donné dans `confidentialite`. Le code postal et la commune du siège accolés au nom du porteur sont retirés ; les colonnes de description longue, de résumé et de liens ne sont pas lues.

**Neutralité.** Aucun qualificatif sur les écarts ; ordres explicites (`ordre.regle`) : projets par nom, éditions par date, départements par code. Les jeux France Relance (enveloppe MTFP) et DITP se recoupent en partie : ils sont publiés côte à côte et jamais additionnés ; `annees.json` garde une colonne par source.

### 2.29 Établissements de santé et médico-sociaux : `sante_etablissements/` (pipeline/sante_etablissements.py)

Référentiel des établissements (FINESS), activité publiée par établissement (Open CCAM, ATIH), prix d'hébergement et tarifs dépendance des EHPAD (CNSA), historique Hospi Diag 2011-2015 et comptes agrégés par catégorie (ATIH). Aucun flux d'argent public par établissement après 2015 : ces données ne sont pas ouvertes, `limites.json` le dit sujet par sujet. Les prix des EHPAD sont des sommes facturées aux résidents, pas une dépense publique. Les subventions du fonds d'intervention régional de l'ARS Pays de la Loire restent dans `subventions/` (2.26) : renvoi seulement. Commandes : `python pipeline/sante_etablissements.py collecter` (réseau : collecteur du dépôt, puis catégories juridiques Sirene, reprise possible ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/sante_etablissements.py produire` (sans réseau). Tests : `pytest tests/test_sante_etablissements.py`.

```
data/lake/sante/ (FINESS - Structures json.gz, extractions FINESS gelées, Open CCAM csv par année, prix CNSA csv,
                  Hospi Diag xlsx) ; data/lake/secu/secu_atih_finances_ebnl.parquet ; data/lake/_cache (Sirene)
     └─> pipeline/sante_etablissements.py ─> site/data/sante_etablissements/index.json, limites.json,
              departements.json, departements/<dep>.json, hospi_diag.json, finances_agregees.json
                                      └─ liens (fichier + id) vers secu/arbre/ (ONDAM) et subventions/ (FIR)
```

| Champ | Sens |
|---|---|
| périmètre | entités géographiques actives du FINESS, hors structures d'exercice libéral (catégorie agrégée 2103), commerce de biens à usage médical dont pharmacies (3201), laboratoires (3101) et entités juridiques personnes physiques (statut 70) ; les exclus sont dénombrés dans `limites.json` |
| `colonnes` (comptes) | `etablissements`, puis six domaines (premier chiffre de la catégorie agrégée FINESS : `hospitalier`, `soins_prevention`, `autres_sanitaires`, `social_medico_social`, `formation`, `non_classe`), trois secteurs (`public`, `prive_non_lucratif`, `prive_commercial` : regroupement du projet d'après les plages de codes du statut juridique FINESS), `ehpad` |
| `actes_ccam_<année>` | nombre d'actes CCAM publiés (médecine, chirurgie, obstétrique, odontologie) ; les lignes de moins de 11 séjours sont absentes de la source : minimum publié, jamais un nombre de patients. Mention exigée par l'ATIH : « source OpenCCAM, année, https://www.scansante.fr/ » |
| `colonnes_prix` | `ehpad_avec_prix` puis médianes en euros par jour : hébergement permanent en chambre seule (hors aide sociale, et places habilitées à l'aide sociale), tarifs dépendance GIR 1-2, 3-4, 5-6 ; valeurs déclarées au 31 décembre ; une valeur hors bornes (20 à 400 € ; 1 à 80 €) reste publiée pour l'établissement mais n'entre pas dans les médianes |
| `departements/<dep>.json` | `communes.lignes` : comptes, prix médians de la dernière année et actes de la dernière année par commune d'implantation ; `etablissements.lignes` : hôpitaux, cliniques, autres établissements relevant de la loi hospitalière, EHPAD et établissements ayant une activité ou un prix publié, avec `finess`, `nom`, entité juridique (`finess_entite_juridique`, `siren`, `entite_juridique`), commune, catégorie, secteur, actes par année, prix déclarés |
| `non_nommes` | établissements seulement comptés, par motif : `personne_physique`, `siren_absent`, `siren_inconnu_de_sirene`, `categorie_juridique_non_verifiee` (Sirene pas encore interrogé : relancer `collecter`), `titre_de_personne_dans_la_denomination` |
| `hospi_diag.json` | 2011 à 2015, par établissement : produits, recettes T2A, recettes MIGAC, charges, résultat, encours de la dette ; `referentiel` D (comptes financiers) ou O (liasses fiscales), jamais additionnés |
| `finances_agregees.json` | ATIH, 2020 à 2024, par secteur, catégorie et activité principale : nombre d'établissements, produits, charges, charges de personnel, résultat principal, encours de la dette ; aucun établissement identifié ; ODbL |
| `liens[]` (index) | `vue` `secu_arbre` (`fichier`, `id`, `md`, exécution 2024 : ONDAM établissements de santé, fonds d'intervention régional, personnes âgées, handicap) ou `subventions` (FIR de l'ARS Pays de la Loire) : même argent vu du financeur, aucun montant réparti par établissement, rien ne s'additionne |
| `ecarts[]` (index) | FINESS en vigueur contre extraction gelée de mai 2026 ; établissements d'Open CCAM absents ou inactifs du FINESS ; EHPAD du FINESS sans prix déclaré |
| `limites.json` | `non_ouvert[]` (`sujet`, `etat`, `ce_qui_existe`, `fichiers`) : comptes par hôpital après 2015, dotations MIGAC, crédits du Ségur, FIR, forfaits soins et dépendance des EHPAD, montants facturés à l'assurance maladie ; `recherche_publique` (requêtes faites et résultats) |

Règles propres : aucune donnée de patient ; aucun professionnel nommé ; un établissement n'est listé que si la catégorie juridique Sirene de son entité juridique est celle d'une personne morale (`pipeline/sirene.py`) et si sa dénomination ne contient pas de titre de personne ; les établissements sociaux et médico-sociaux autres que les EHPAD sont seulement comptés ; adresse, téléphone, courriel et coordonnées géographiques ne sont jamais repris ; une valeur absente ou marquée non disponible à la source reste null. Licences : Licence Ouverte (FINESS, Hospi Diag), ODbL (ATIH), non précisée pour les prix des EHPAD (la notice de la CNSA renvoie à la loi pour une République numérique).

### 2.30 Marchés publics de tous les acheteurs : `marches/` (pipeline/marches.py)

Producteur : `pipeline/marches.py`. Étend `beneficiaires/marches_etat.json` (services de l'État, 2024, 2.9), qui reste produit par `pipeline/beneficiaires.py`, à tous les acheteurs des données essentielles de la commande publique (DECP) consolidées : État, collectivités, hôpitaux, établissements publics, autres. Marchés notifiés de 2019 à 2025. Sources déclarées dans `collecte/catalogue.json` : `benef_decp` (fichier `decp.parquet`, zone restreinte car il contient des entrepreneurs individuels) et `marches_decp_doublons_sources` (même jeu data.gouv.fr `608c055b35eb4e6ee20eb325`, Licence Ouverte 2.0, mise à jour quotidienne) ; stock SIRENE des unités légales partagé avec `pipeline/local.py`. Commandes : `python pipeline/marches.py collecter` (réseau, par `collecte/collecte.py`), `python pipeline/marches.py produire [--sortie DOSSIER]` (sans réseau, environ 30 s, reproductible octet pour octet : sommes en entiers). Tests : `pytest tests/test_marches.py` (jeu synthétique, sans entrepôt).

```
data/lake/_restreint/beneficiaires/benef_decp/ (DECP consolidées)      data/lake/marches/ (doublons entre sources)
stock SIRENE (catégorie juridique, dénomination, statut de diffusion)
     └─> pipeline/marches.py ─> site/data/marches/index.json, annees.json, categories.json, departements.json,
                                departements/<code>.json (106 fichiers, chacun < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `marches/index.json` | `marches_index` | `regles_qualite[]` (`id`, `regle`, `lignes`, `montant_eur` ; null si le motif n'a pas de montant), `anomalies_source` (lignes « aberrant » et « suspect », montants déclarés), `totaux` (lignes source, actuelles, dédoublonnées, retenues ; marchés, montant retenu, acheteurs, titulaires nommés, `nommes_eur`, `agrege_confidentialite`), `par_annee[]`, `repere_oecp`, `recoupements[]`, `centrales_achat`, `doublons_entre_sources`, `methode[]`, `limites[]`, `regle_personnes`, `sources[]`, `sources_inaccessibles[]`, `recherche_publique`, `fichiers` |
| `marches/annees.json` | `marches_annees` | `par_annee[]` : `marches`, `lignes`, `acheteurs`, `total_eur`, `nommes_eur`, `agrege_confidentialite`, `par_nature[]`, `par_type[]`, `ecartes` (lignes de l'année écartées : montant non renseigné, aberrant, suspect, négatif, SIRET du titulaire invalide, avec leur montant déclaré) |
| `marches/categories.json` | `marches_categories` | `categories[]` : `categorie`, `origine` (`decp` : catégorie du jeu ; `sirene` : dérivée de la catégorie juridique), `definition`, `acheteurs`, `marches`, `total_eur`, `par_annee[]` |
| `marches/departements.json` | `marches_departements` | `departements[]` : `departement`, `nom`, `marches`, `acheteurs`, `total_eur`, `montants_eur[]` aligné sur `annees`, `fichiers[]` ; `non_localise` (département absent de la source) |
| `marches/departements/<code>.json` | `marches_departement` | un département : `par_categorie[]`, `acheteurs[]` (`siren`, `denomination`, `categorie_juridique`, `categorie`, `marches`, `total_eur`, `montants_eur[]`, `titulaires[]` : 10 premiers titulaires nommés avec `marches` et `montant_eur`, `autres_titulaires {nombre, montant_eur}`, `agrege_confidentialite {montant_eur, lignes}`), `acheteurs_non_nommes`, `acheteurs_total` ; découpé en `<code>_1.json`, `<code>_2.json` (`partie`, `parties`) au-delà de 4,5 Mo |

**Règles de qualité (publiées et comptées).** Chaque ligne écartée est comptée dans le premier motif rencontré, dans cet ordre, avec son montant déclaré ; aucune n'est supprimée en silence : (1) lignes `donneesActuelles` seulement (dernière version publiée du marché) ; (2) une ligne par couple (`uid`, titulaire), celle de la modification la plus récente ; (3) nature normalisée (`MARCHE`, `marché`, `Accord cadre`... ramenés à un libellé unique ; concessions et délégations de service public hors champ ; une valeur inconnue arrête la production) ; (4) année = année de la notification initiale (plus petite modification publiée), date absente ou impossible (avant 2000 ou postérieure à la collecte) écartée, année hors 2019-2025 comptée à part ; (5) montant non renseigné : `null`, jamais 0 ; (6) lignes marquées « aberrant » **et** « suspect » par le producteur du jeu écartées, total publié à part (`regles_qualite`, `anomalies_source`, `annees.json`) ; (7) montant négatif écarté ; (8) SIRET du titulaire à 14 chiffres à clé de contrôle valide (La Poste : règle propre), sinon ligne écartée. Conservation contrôlée : montant retenu + montant de chaque motif = `totaux.montant_dedoublonne_eur`.

**Montants.** Euros HT : montant notifié, ou montant maximum estimé pour un accord-cadre ; ce n'est pas un montant payé. Marché à plusieurs titulaires : montant réparti à parts égales. `marches` compte des identifiants `uid` distincts. `montants_eur[]` : `null` pour une année sans ligne retenue. Catégorie d'acheteur : celle du jeu quand elle existe (État, Commune, Groupement de communes, Syndicat mixte, Département, Département outre-mer, Région, Établissement hospitalier, EPIC), sinon dérivée de la catégorie juridique SIRENE (établissements publics administratifs nationaux et locaux, organismes consulaires, GIP, sociétés, organismes de sécurité sociale, associations, non identifié). Département : celui de l'établissement acheteur.

**Repère officiel et écarts, publiés, jamais tranchés.** `repere_oecp` : total du recensement économique de la commande publique 2024 (OECP : 233,3 Md€, 223 383 marchés), saisi à la main avec sa source ; la page officielle refuse les scripts (HTTP 403, non contourné), la valeur est relevée sur une page accessible qui cite l'étude (`page_consultee`), sinon `montant_eur` vaut `null`. Les deux périmètres diffèrent (`lecture_ecart`) ; les montants ne sont ni additionnés ni corrigés. `recoupements[]` : écart avec `beneficiaires/marches_etat.json` (même source, règles différentes). `centrales_achat` : montants des centrales d'achat (UGAP, Resah...) comme acheteur et comme titulaire ; le même achat peut figurer deux fois (marché de la centrale avec son fournisseur, marché de l'acheteur avec la centrale) : risque signalé, aucun montant retranché. Un accord-cadre et ses marchés subséquents peuvent aussi être comptés tous les deux (`limites`).

**Règle personnes physiques (bloquante).** Un acheteur ou un titulaire n'est nommé que si sa catégorie juridique SIRENE est celle d'une personne morale (`sirene.personne_morale`) et si son statut de diffusion n'est pas partiel ; le nom publié est la dénomination SIRENE. Entrepreneurs individuels, SIREN absents du stock, unités à diffusion partielle : agrégés dans `agrege_confidentialite` (`dont_personnes_physiques_eur`, `dont_diffusion_partielle_eur`, `dont_siren_introuvable_eur`), jamais nommés. Colonnes des DECP jamais lues : noms d'acheteur et de titulaire, objet du marché, communes, coordonnées, lieu d'exécution. **Ordre neutre** écrit dans `ordre` : acheteurs et titulaires par montant décroissant puis SIREN, départements par code, catégories dans un ordre fixe.

### 2.31 Aide au développement : `aide_developpement/` (pipeline/aide_developpement.py)

Producteur : `pipeline/aide_developpement.py`. Sources déclarées dans `collecte/catalogue.json` (`etat_aide_publique_developpement`, `apd_afd_iati`, `apd_ocde_dac2a`, `apd_ocde_dac5`, `apd_expertise_france_contrats` en zone restreinte, `apd_proparco`) et collectées par `python collecte/collecte.py <ids>` (réseau ; un refus 403/429 n'est jamais contourné) ; `python pipeline/aide_developpement.py produire [--sortie DOSSIER]` (sans réseau ; lit aussi `arbre/racine.json` et `arbre_lfi2025/racine.json`). Tests : `pytest tests/test_aide_developpement.py`. Fichiers compacts, avec `millesime`, `source`, `unite`, `avertissement`, `collecte_le`.

```
DG Trésor, APD déclarée au CAD (activités, k€) ───────────┐
AFD, publication IATI par pays (concours, transactions) ──┤
OCDE SDMX : DAC2A (pays), DAC5 (secteurs), M$ courants ───┼─> pipeline/aide_developpement.py ─> site/data/aide_developpement/*.json
Expertise France (contrats > 15 000 €), Proparco ─────────┤
site/data/arbre : mission « Aide publique au développement » ┘
```

**Règle centrale : rien ne s'additionne.** Six grandeurs (`index.json`, `grandeurs[]` : `credits_budgetaires`, `apd_declaree`, `afd`, `proparco`, `expertise_france`, `ocde`), chacune avec `producteur`, `perimetre`, `methode`, `unite`, `financement` (toujours `null` : aucun texte rédigé par le site) et `financement_citations` (identifiants de `citations[]`). Elles se recouvrent en partie et ne sont jamais sommées. Dons et prêts sont toujours dans des colonnes séparées, sans colonne de total commun (le schéma de `totaux` refuse toute clé supplémentaire). `financement_des_prets` ne contient que `perimetre` et `citations` : renvois vers `citations[]`, citations mot pour mot (`auteur`, `document`, `url`, `page`, `texte`, `consulte_le`) de la page de l'AFD « Le prêt, premier outil financier du groupe AFD » et du projet annuel de performances 2026 (programmes 110 et 365). **Textes explicatifs sourcés** : chaque fichier porte `sources_textes`, qui associe chaque champ texte explicatif (`avertissement`, `note`, `lecture`, `constat`, `limites`, `definitions`, `regle`, `motif`, `perimetre`, `methode`…, chemin avec `*` pour les indices) à sa source : `traitement` (règle appliquée par le pipeline), identifiant de `sources[]`, `arbre` ou `citation:<id>` ; un champ sans source fait échouer la production et les tests.

| Fichier | Contenu |
|---|---|
| `aide_developpement/index.json` | `regle`, `grandeurs[]`, `financement_des_prets`, `credits_budgetaires.vues[]` (mission et programmes de `arbre/` et `arbre_lfi2025/`, lien `fichier`, Md€), `totaux.<grandeur>` (`colonnes`, `lignes` par année), `ecarts[]` (`annee`, `comparaison`, `source`, `montant`, `autre_source`, `autre_montant`, `ecart`, `ecart_pct`, `lecture` : publiés, jamais arbitrés), `fichiers[]`, `sources[]` (`licence`, `collecte_le`), `sources_inaccessibles[]`, `limites[]`, `recherche_publique` |
| `aide_developpement/apd_declaree.json` | APD déclarée à l'OCDE (DG Trésor), euros, déclarations 2018 à 2024 : `par_annee` (type de flux × type de financement : `engagements_eur`, `verse_eur`, `equivalent_don_eur`, `percu_eur`), puis, pour le flux APD seul, `par_canal`, `par_agence`, `par_secteur`, `par_pays` avec les colonnes `colonnes_ventilations` (`dons_verses_eur`, `prets_verses_eur`, `autres_verses_eur`, `equivalent_don_eur`, `percu_eur`) ; `pays[]` (`code` ISO à trois lettres ou `R<code>` pour un regroupement régional, `categorie_cad`, `region`) |
| `aide_developpement/afd.json` | concours de l'AFD (IATI), euros, 2018 à l'année en cours (`annees_partielles`) : `par_annee`, `par_pays`, `par_secteur`, toujours par `flux` (`apd`, `autres_apports_publics`) avec `colonnes_montants` (`dons_engages_eur`, `prets_engages_eur`, `dons_verses_eur`, `prets_verses_eur`) ; `par_annee.concours_engages` ; `couverture`, `ecartes[]` (transactions avant 2018, instantané de 2023 non lu), `methode` |
| `aide_developpement/ocde.json` | millions de dollars courants, non convertis : `versements_par_pays` (DAC2A : dons, prêts bruts, remboursements, prêts nets, APD brute, APD nette, multilatérale imputée ; `ensemble_pays_en_developpement`), `engagements_par_secteur` (DAC5 : engagements d'APD, dont dons, autres apports publics ; `secteurs[].niveau` emboîtés) |
| `aide_developpement/expertise_france.json` | contrats de plus de 15 000 € : `lignes` (`annee`, `pays`, `bailleur`, `type`, `contrats`, `montant_initial_maximal_eur`), `par_bailleur`, `par_pays` (marchés et subventions d'un côté, plafonds d'accords-cadres de l'autre), `ecartes[]` |
| `aide_developpement/proparco.json` | financements signés : `par_annee` et `lignes` (`annee`, `pays`, `instrument` : `pret`, `participation`, `garantie`, `don`, `accompagnement_technique`, `obligation`, `non_renseigne`) |

**Personnes physiques (bloquant).** Aucun bénéficiaire, attributaire, client ni expert n'est nommé : ces sources n'ont pas de SIREN, la règle `sirene.personne_morale` ne peut pas s'appliquer, tout est donc agrégé. Les colonnes de noms, de contact et de texte libre (titres, objets, descriptions) ne sont jamais lues. Les contrats d'experts individuels d'Expertise France sont exclus des ventilations et donnés en un seul total dans `ecartes`. Un accord-cadre est un plafond, compté à part ; le montant d'un contrat est un montant initial maximal, pas une dépense.

**Absences et ordre.** `null` = valeur absente à la source, jamais 0. Lignes par année puis par ordre alphabétique (`ordre.regle`), aucun classement par montant. Pays : codes à trois lettres communs à `apd_declaree`, `afd` et `ocde` (Kosovo : `XKX` pour la DG Trésor et l'AFD, `XKV` pour l'OCDE) ; Expertise France et Proparco gardent les noms de leur source.

### 2.32 Formation professionnelle : `formation/` (pipeline/formation.py)

Compte personnel de formation (CPF), droit individuel à la formation des élus locaux et FIPHFP : ce que la Caisse des dépôts publie sur les dispositifs qu'elle gère (opendata.caissedesdepots.fr, Licence Ouverte 2.0). Agrégats seulement. Commandes : `python pipeline/formation.py collecter` (réseau ; le portail coupe souvent, reprises espacées ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/formation.py produire` (sans réseau). Tests : `pytest tests/test_formation.py`.

```
opendata.caissedesdepots.fr (API Explore v2.1, agrégats `group_by` calculés par le portail : le jeu des formations
engagées, 2,2 millions de lignes, n'est jamais exporté en entier) ─> data/lake/formation/*.csv
France compétences, rapport sur l'usage des fonds (PDF) ; Insee, répertoire Sirene (catégorie juridique)
     └─> pipeline/formation.py ─> site/data/formation/index.json, cpf_mois.json, cpf_departements.json,
                                    cpf_certifications.json, cpf_organismes.json, cpf_usagers.json, elus.json, fiphfp.json
                                    └─ liens (fichier + id) vers operateurs/operateurs.json (France compétences) et arbre/ (programme 103)
```

| Fichier | Schéma | Contenu | Unité | Millésime |
|---|---|---|---|---|
| `formation/index.json` | `formation_index.schema.json` | CPF par année : dossiers, montant engagé, part de chaque financeur, statuts ; résumés élus et FIPHFP ; liens, écarts entre sources, sources, recherche préalable | €, dossiers | 2020 à 2026 |
| `formation/cpf_mois.json` | `formation_cpf_mois.schema.json` | CPF par mois de validation, par financeur et par statut | €, dossiers | 2020 à 2026 |
| `formation/cpf_departements.json` | `formation_cpf_departements.schema.json` | CPF par année et département du lieu de formation ; par modalité (présentiel, à distance, mixte) | €, dossiers | 2020 à 2026 |
| `formation/cpf_certifications.json` | `formation_cpf_certifications.schema.json` | CPF par certification (400 premières par montant cumulé, reste additionné) et par référentiel | €, dossiers | 2020 à 2026 |
| `formation/cpf_organismes.json` | `formation_cpf_organismes.schema.json` | entrées et sorties de formation par organisme (SIREN), montant approché | stagiaires, € approchés | 2022 à 2026 |
| `formation/cpf_usagers.json` | `formation_cpf_usagers.schema.json` | dossiers entrés en formation par région de domicile, sexe, âge, situation | dossiers, € | 2020 à 2026 |
| `formation/elus.json` | `formation_elus.schema.json` | formation des élus locaux par type de mandat, dispositif et organisme | dossiers, €, heures | 2022 à 2026 |
| `formation/fiphfp.json` | `formation_fiphfp.schema.json` | FIPHFP : aides aux employeurs publics par département, conventions par région, par versant | € courants | aides 2008 à 2025, conventions 2010 à 2025 |

| Champ | Sens |
|---|---|
| `montant_eur`, `dossiers` (CPF) | dossiers validés non annulés (`retenus` : `realise`, `realise_partiellement`, `en_cours`) ; montant engagé = somme des prix des formations, pas un montant payé ; les dossiers annulés ou rejetés sont publiés dans `par_statut.annule` |
| `financeurs_eur`, `financeurs_pct` | `france_competences` (droits CPF mobilisés, nets des dotations des entreprises), `titulaire` (reste à charge), `etat`, `france_travail`, `regions`, `opco`, `entreprises`, `cec` ; `dossiers_cofinances` : dossiers où l'abondement est positif |
| `complete` | faux pour l'année en cours (moins de douze mois, dossiers encore annulables) |
| départements | `colonnes` = dossiers, montant, part France compétences, part titulaire, autres financeurs, dossiers annulés, montant annulé ; `lieu_non_communique` : dossiers sans lieu (dont formations à distance), rattachés à aucun département |
| certifications | `referentiel` (`RNCP`, `RS`, `Autre` = hors répertoires, identifié par l'intitulé) ; `annees.<a>` = dossiers, montant, part France compétences, prix moyen |
| `organismes[]` (CPF) | `siren`, `nom` (dénomination Sirene), `categorie_juridique`, `etablissements`, `annees.<a>` = entrées, sorties totales, sorties partielles, `montant_approche_eur` ; `agreges` : personnes morales non listées, entrepreneurs individuels, absents du répertoire, non vérifiés |
| `estimation` | `statut: "approché"`, producteur (le projet), périmètre, méthode (entrées x prix moyen de la certification la même année), limites ; `totaux.<a>.controle_estimation` compare la somme des estimations au montant engagé RNCP et RS |
| `par_mandat.<a>.<dispositif>[]` (élus) | `mandats` (types de mandat contenus dans la cellule), `valeurs` = dossiers, montant engagé, droits de l'élu, heures |
| `aides`, `conventions` (FIPHFP) | par année et département (ou région) : `fpe`, `fph`, `fpt` ; `employeurs_nationaux` ; `totaux.<a>.non_localise` ; les deux séries ne sont pas additionnées |
| `liens[]` (index) | `vue` (`operateurs`, `arbre_etat`), `fichier`, `id`, `lecture` : même argent vu du côté du financeur (France compétences, programme 103), jamais additionné au CPF |
| `ecarts[]` (index) | montant du jeu ouvert (`cdc_formations_engagees`) contre montant net publié par France compétences (`france_competences_ruf_2025`), `ecart`, `ecart_pct`, `lecture_ecart` ; `verification_documents` : valeurs citées retrouvées dans le PDF collecté |

Règles propres. Personnes : un organisme n'est nommé que si `sirene.personne_morale(catégorie juridique)` est vrai, sous la dénomination du répertoire Sirene ; la raison sociale saisie sur la plateforme n'est pas téléchargée ; entrepreneurs individuels, SIREN absents du répertoire ou non vérifiés sont additionnés. Élus : le jeu d'origine nomme chaque élu, les colonnes nom, prénom, genre et lieu de mandat ne sont jamais demandées au portail (requêtes `group_by` seulement) ; une cellule de moins de 5 dossiers n'est jamais publiée seule (fondue avec d'autres types de mandat) ; un organisme est nommé à partir de 5 dossiers cumulés, sans détail par année. Absences : une valeur vide à la source reste `null` (FIPHFP), jamais 0. Ordres : certifications par montant cumulé décroissant, organismes par entrées cumulées décroissantes puis SIREN, règle écrite dans `ordre`. Sources non reprises : `sources_inaccessibles` (DARES, montant versé par organisme, années antérieures).

### 2.33 L'État actionnaire : `etat_actionnaire/` (pipeline/etat_actionnaire.py)

Producteur : `pipeline/etat_actionnaire.py`. Sources déclarées dans `collecte/catalogue.json` (`etat_actionnaire_*`, domaine `etat_actionnaire`) et collectées par `python collecte/collecte.py etat_actionnaire_plf25_recettes_bg etat_actionnaire_plf24_recettes_bg etat_actionnaire_plf25_recettes_cas etat_actionnaire_plf24_recettes_cas etat_actionnaire_lfi23_recettes_cas etat_actionnaire_plf25_depenses_destination etat_actionnaire_plrg_annexes etat_actionnaire_documents etat_actionnaire_valeur_portefeuille` (réseau ; les rapports relatifs à l'État actionnaire, le rapport annuel de performances 2025 du compte et le rapport de présentation du compte général de l'État 2025 nomment des dirigeants : ils vont dans `data/lake/_restreint/etat_actionnaire/`, seuls des montants et des citations sans nom en sont repris ; un refus 401/403 n'est jamais contourné : le site de l'Agence des participations de l'État, qui répond 403, est listé dans `sources_inaccessibles`) ; `python pipeline/etat_actionnaire.py collecter` (catégorie juridique des entités nommées, API Recherche d'entreprises) ; `python pipeline/etat_actionnaire.py produire [--sortie DOSSIER]` (sans réseau ; échoue si une citation du Sénat n'est plus dans le document collecté ou si un total ne se retrouve pas). Tests : `pytest tests/test_etat_actionnaire.py`. Fichiers compacts, avec `millesime`, `source`, `unite`, `avertissement`, `collecte_le`.

```
data.economie : recettes du budget général (PLF 2024, 2025), recettes des CAS (LFI 2023, PLF 2024, 2025) ─┐
data.economie : dépenses selon destination (PLF 2025), annexes CSV des PLRG 2023, 2024, 2025 ────────────┼─> pipeline/etat_actionnaire.py ─> site/data/etat_actionnaire/*.json
projet annuel de performances 2026 du compte (PDF), annexe 21 du Sénat (PDF), Insee (xlsx) ──────────────┤
rapports relatifs à l'État actionnaire 2024 et 2025, RAP 2025 du compte, compte général 2025 (PDF) ───────┘
```

Présentation : dividendes reçus, cessions, opérations en capital comme flux bruts par année, en comptabilité budgétaire, sans qualification. Montants en euros (`*_eur`), sauf la série longue des dividendes (milliards d'euros, `*_md`). `par_annee` : année (chaîne) > mesure > montant ; mesures : `plf_eur`, `lfi_eur` (jeux des lois de finances ; projet annuel de performances pour le compte en 2025), `lfi_plrg_eur`, `lfr_plrg_eur`, `prevision_revisee_eur`, `evaluation_eur`, `report_entrant_eur`, `credits_ouverts_eur`, `execution_eur`, `report_sortant_eur` (PLRG). Une mesure absente n'est pas publiée par les sources : jamais 0 par défaut ; un total n'est calculé que si toutes ses lignes portent la mesure.

| Fichier | Contenu |
|---|---|
| `etat_actionnaire/index.json` | `definitions` (dividendes, cessions, recapitalisations, versement du budget général, compte), `fichiers[]`, `chiffres_cles` (exécution de la dernière année), `liens.recettes` (`recettes.json` : impôts en comptabilité nationale, les produits des participations n'y figurent pas) et `liens.arbre` (`arbre/racine.json` : `noeuds[]` des programmes 367 et 369 du budget général qui versent au compte, `present`, `id`, `md`, `execution_2024_plrg_eur` ; les programmes 731 et 732 sont hors de l'arbre), `sources[]` (URL, licence), `sources_inaccessibles[]`, `limites[]`, `recherche_publique.trouvailles[]` (verdict, licence, date) ; `valeur_portefeuille` : `agence` (estimation de l'Agence des participations de l'État pour son périmètre, statut « approché », `serie[]` au 30 juin 2022 à 2025 : `date`, `valeur_md`, `valeur_cotee_md`, `entreprises`, `citations[]` avec `page` et `texte` exact ; `cotees_fin_2025` ; `methode_citation`) et `bilan_etat` (compte général de l'État au 31 décembre 2025, statut « tracé » : `valeur_md`, entités contrôlées et non contrôlées en nombre et en milliards d'euros) ; deux mesures côte à côte, jamais additionnées |
| `etat_actionnaire/flux.json` | `dividendes.lignes[]` (lignes 2110, 2116, 2199 des recettes non fiscales), `dividendes.total`, `dividendes.serie_longue` (dividendes perçus par l'État actionnaire 2014 à 2025, numéraire et actions, projet annuel de performances ; périmètre différent, jamais additionné) ; `compte.recettes.lignes[]` (lignes 01 à 06, `nature`, `detail_execution` par ligne d'exécution), `total`, `hors_versement_budget_general` ; `compte.depenses.programmes[]` (731, 732, `actions[]` en prévision), `composition_2025_citee` (montants cités par le Sénat, `citation`, `page`) ; `compte.solde.par_annee` (`debut_eur`, `recettes_eur`, `depenses_eur`, `fin_eur`) ; `budget_general_vers_compte.programmes[]` (367, 369) ; `ecarts_entre_sources[]` (deux montants de sources différentes pour un même objet, publiés sans être tranchés) ; `rapprochement_senat` |
| `etat_actionnaire/entites.json` | `dividendes_par_ligne_d_execution[]` : `ligne`, `code_execution`, `libelle_source` (nomenclature budgétaire), `categorie_source`, `entite` (`siren`, `denomination`, `categorie_juridique`) ou `null` pour une ligne générique, `execution_eur` par année ; `non_verifiees` (lignes dont l'entité n'est pas une personne morale vérifiée : agrégées, jamais nommées) ; `operations_citees.operations[]` (opérations de 2025 relevées dans le texte de l'annexe du Sénat : `entite`, `mentions[]` avec `nature`, `montant_eur`, `citation`, `page`) ; `ordre` |
| `etat_actionnaire/societes_controlees.json` | Insee : `serie[]` 1995 à 2022 (`societes`, `effectifs_milliers`, `part_emploi_salarie_pct`), `activites[]` fin 2021 et fin 2022 (`niveau`, `parent`, `secret_statistique[]` : valeur `null`) |

**Confidentialité.** Une entité n'est nommée que si `sirene.personne_morale(catégorie juridique)` est vrai pour son SIREN (rapproché du libellé budgétaire par le projet, vérifié par `collecter`) ; sinon sa ligne est agrégée dans `non_verifiees`. Aucun nom de personne physique n'est repris des documents parlementaires. **Neutralité.** Aucun qualificatif ; les appréciations du rapport du Sénat ne sont pas reprises, seuls ses montants le sont, avec leur citation exacte. Le tableau des opérations par entreprise de ce rapport, publié en image, n'est pas repris. Contrôles à la production : chaque valeur des participations se lit mot pour mot à sa page du document collecté (lecture colonne par colonne), sinon la production s'arrête ; rapprochements Bpifrance (établissement public, SIREN 483790069) et TSA (SIREN 542089750) contrôlés dans l'annexe « Participations directes de l'État » du rapport 2025 et au répertoire Sirene (personnes morales actives) ; somme des lignes d'exécution = total publié (1 € près) ; recettes et dépenses du compte = situation comptable (1 € près) ; lignes publiées + agrégat = total des dividendes.

### 2.34 Éducation et recherche : `education_recherche/` (pipeline/education_recherche.py)

Projets de l'ANR (programmes d'investissements d'avenir et France 2030, éditions 2006 à 2026 ; projets financés 2005 à 2009), subventions et dotations de trois régions aux lycées (Île-de-France 2021-2023, Centre-Val de Loire 2017-2025, Pays de la Loire 2017-2020), budgets des collectivités pour la recherche et l'enseignement supérieur (2006-2025), effectifs étudiants par établissement (2006-07 à 2024-25) et coût par étudiant calculé. Sources déclarées dans `collecte/catalogue.json` (entrées `edrech_*`). Commandes : `python pipeline/education_recherche.py collecter` (réseau, par `collecte/collecte.py` ; un refus est noté, jamais contourné), `python pipeline/education_recherche.py produire [--sortie DOSSIER]` (sans réseau ; stock SIRENE des unités légales partagé avec `local.py`, lecture seule de `beneficiaires/france2030.json`). Tests : `pytest tests/test_education_recherche.py`.

```
data/lake/_restreint/education_recherche/ (ANR : partenaires et projets ; colonnes du responsable scientifique jamais lues)
data/lake/education_recherche/ (annuaire de l'éducation, budgets des collectivités, effectifs, lycées de trois régions)
stock SIRENE (catégorie juridique, dénomination)          site/data/beneficiaires/france2030.json (lien, lecture seule)
tableur Insee du compte de l'éducation (DEPP)
     └─> pipeline/education_recherche.py ─> site/data/education_recherche/index.json, anr_etablissements.json,
                anr_projets.json, lycees/<région>.json, collectivites_esr.json, etudiants.json,
                compte_education.json (chacun < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `education_recherche/index.json` | `education_recherche_index` | `sources[]` (titre, producteur, page, licence, millésime, verdict, entrées du catalogue), `licences.odbl[]`, `totaux` (un par source, jamais additionnés), `cout_par_etudiant` (statut, formule, série nationale), `ecarts[]`, `liens[]` vers `beneficiaires/france2030.json`, `sorties`, `limites`, `sources_inaccessibles[]`, `recherche_publique` |
| `education_recherche/anr_etablissements.json` | `education_recherche_anr_etablissements` | deux blocs, `pia_france2030` et `anr_2005_2009` : `colonnes` = `siren`, `denomination`, `categorie_juridique`, `methode_appariement`, `categories_source`, `participations`, `projets_coordonnes`, montant, `lignes_sans_montant`, `premiere_edition`, `derniere_edition`, `lien_france2030` ; `nommes`, `non_nommes` (`par_categorie[]`, `motifs`), `total`, `total_projets`, `ordre` |
| `education_recherche/anr_projets.json` | `education_recherche_anr_projets` | `pia_france2030` : `par_annee[]` (édition), `par_action[]`, `par_region[]` (libellé publié) ; `anr_2005_2009` : `par_annee[]`, `par_programme[]` (60 premiers + `par_programme_autres`) ; `ecarts[]` |
| `education_recherche/lycees/<région>.json` | `education_recherche_lycees` | une région (`11`, `24`, `52`) : `colonnes` = `uai`, `siren`, `nom`, `categorie_juridique`, `secteur`, `type`, `code_commune`, `departement`, `academie`, `total_eur`, `montants_eur[]` (alignés sur `annees`) ; `nommes`, `non_nommes` (`motifs`), `par_annee[]`, `par_dispositif[]`, `par_commune[]`, `par_departement[]`, `nature_des_montants`, `controles[]` (Centre-Val de Loire 2017) |
| `education_recherche/collectivites_esr.json` | `education_recherche_collectivites_esr` | `national[]` par année (`qualite`, `total_eur`, `rt_eur`, `esve_eur`, `par_type`, `par_nature`), `regions[]` (séries `rt_eur`, `esve_eur`, `par_type.<CR\|CD\|COMS_EPCI>` alignées sur `annees`), `natures[]`, `types_collectivite` |
| `education_recherche/etudiants.json` | `education_recherche_etudiants` | `colonnes` = `id_paysage`, `uai[]`, `siren`, `categorie_juridique`, `nom`, `type`, `typologie`, `code_commune`, `commune`, `departement`, `academie`, `region`, `double_compte`, `etudiants[]`, `etudiants_hors_cpge[]` (alignés sur `annees`) ; `par_commune[]`, `par_departement[]`, `par_region[]` ; `cout_par_etudiant` (`statut`, `formule`, `perimetre`, `limites`, `national[]`, `regions[].valeurs[]`, chaque valeur avec `mention`) |
| `education_recherche/compte_education.json` | `education_recherche_compte_education` | compte de l'éducation (DEPP), tableur de l'Insee (France, portrait social 2025, fiche « Dépenses d'éducation ») : `financement_initial` (`annees`, `provisoire[]`, `financeurs[]` = `id`, `libelle`, `libelle_source`, `parent`, `part_pct[]` ; `familles_et_entreprises` = `annee`, `menages_pct`, `entreprises_pct` ; `controle_somme[]`), `die` (dépense intérieure d'éducation et dépense moyenne par élève, euros courants et constants), `die_serie` (1980 à 2024, part dans le PIB), `depense_moyenne_par_niveau` (`annee`, `niveaux[]` = `degre`, `niveau`, `ensemble_du_degre`, `depense_moyenne_eur`), `depense_moyenne_evolution` (euros constants, ensemble et trois degrés) |

**ANR.** La source ne publie aucun SIREN. Un organisme est rattaché à une unité légale par `denomination_identique` (dénomination identique après normalisation à celle d'une seule personne morale du stock SIRENE : une seule unité active, ou une seule unité s'il n'en reste aucune active) ou par `regle_organisme_national` (délégation ou centre dont la dénomination commence par le nom ou le sigle du CNRS, de l'Inserm, d'Inria, du CEA, d'INRAE, de l'IRD ou de l'AP-HP ; jamais pour une filiale). Le nom publié est la dénomination SIRENE. Programmes d'investissements d'avenir et France 2030 : l'aide est publiée par projet ; `aide_projets_coordonnes_eur` est l'aide des projets dont l'établissement est le coordinateur, pas la somme qu'il reçoit. 2005-2009 : `aide_allouee_eur` est l'aide publiée par partenaire ; un partenaire sans aide publiée est compté dans `lignes_sans_montant`, jamais 0. Conservation : `nommes` + `non_nommes` = `total` (participations, projets coordonnés, montant). **Lien avec France 2030** : `beneficiaires/france2030.json` (2.9) reste la source des montants par bénéficiaire ; rien n'en est recopié. `lien_france2030` vaut vrai quand le SIREN figure parmi les bénéficiaires nommés de l'opérateur ANR ; `ecarts[]` publie les deux montants (éditions 2021 à 2025 de l'ANR contre opérateur ANR du jeu France 2030), jamais additionnés.

**Lycées.** Clé d'un bénéficiaire : UAI, sinon SIREN (tiers sans UAI en Île-de-France). SIREN : SIRET de la source (Île-de-France) ou de l'annuaire de l'éducation ; nom, commune (code Insee), département et académie : annuaire de l'éducation (établissements ouverts). Année : décision (Île-de-France), versement (Centre-Val de Loire), début de la campagne (Pays de la Loire). Les montants n'ont pas la même nature d'une région à l'autre (`nature_des_montants`) et ne se comparent pas. Centre-Val de Loire 2017 : une colonne par dotation, ramenée à une ligne par dotation ; la somme est comparée au total publié (`controles[]`). `par_commune` et `par_departement` comptent tous les bénéficiaires, nommés ou non ; `code_commune` null : bénéficiaire sans UAI ou absent de l'annuaire.

**Coût par étudiant.** Valeur calculée par le site, marquée `statut = "calculé"` à chaque niveau, avec sa `formule` : dépenses des collectivités de la région pour l'enseignement supérieur et la vie étudiante de l'année N, divisées par les inscriptions principales hors doubles inscriptions en CPGE de l'année universitaire N-1/N dans les établissements publics sous tutelle du ministère dont le siège est dans la région, hors établissements-composantes déjà comptés. Ce n'est pas la dépense totale par étudiant (`limites`). Outre-mer : `correspondance_regions` rapproche le code Insee de la région (effectifs) du code 971 à 976 (budgets). Null quand le budget ou l'effectif manque.

**Règle personnes physiques (bloquante).** Colonnes jamais lues (`COLONNES_LUES` du module fait foi, contrôlé par les tests) : nom, prénom et ORCID du responsable scientifique, ville du partenaire (ANR) ; adresse, téléphone, télécopie, courriel, site web (annuaire, exclus dès l'export) ; tiers et intitulé du dossier (Île-de-France) ; appellation saisie, adresse et géolocalisation (Pays de la Loire). Un bénéficiaire n'est nommé que si `sirene.personne_morale` est vrai pour sa catégorie juridique lue dans le stock SIRENE ; sinon il est agrégé (`non_nommes`, avec son motif). Les établissements d'enseignement supérieur du jeu des effectifs sont des établissements publics sous tutelle du ministère, nommés avec leur UAI. Libellés de dispositif : filtre de noms de `pipeline/local.py`, sinon agrégés dans `par_dispositif_autres`.

**Compte de l'éducation (ajout du 18/11/2026).** `compte_education.json` reprend, sans calcul, les quatre figures du tableur de l'Insee dont les données viennent du compte de l'éducation de la DEPP : part de chaque financeur dans le financement initial de la dépense intérieure d'éducation (État, dont ministères de l'éducation, ligne « dont » jamais ajoutée ; collectivités ; autres administrations et caisses d'allocations familiales ; entreprises ; ménages, c'est-à-dire les familles), dépense intérieure d'éducation, dépense moyenne par élève ou étudiant (tous financeurs, y compris apprentis) par niveau de l'école au supérieur, et son évolution en euros constants. `familles_et_entreprises` donne les deux parts de la dernière année, publiées séparément, jamais additionnées. Années provisoires listées (`annees_provisoires`, `provisoire[]`). Ces montants couvrent toute la dépense d'éducation : ils ne se comparent ni ne s'additionnent au coût par étudiant calculé par le site (`etudiants.json`). Aucun jeu ouvert du compte n'existe sur data.education.gouv.fr ni data.gouv.fr (recherche du 18/11/2026) ; les pages et tableaux de la DEPP sur education.gouv.fr (Repères et références statistiques, chapitre 10) refusent l'accès aux robots (403) : notés dans `sources_inaccessibles`, non contournés. `index.json` ajoute `fichiers.compte_education`, `sorties.national`, `totaux.compte_education` et la source `compte_education` ; aucun champ existant n'est renommé.

**Absences : null, jamais 0 (correctif du 18/11/2026).** Budgets des collectivités : la source ne publie aucune ligne « enseignement supérieur et vie étudiante » de 2006 à 2014 ; `national[].esve_eur` et `national[].total_eur` y valent null (avant : 0), avec `categories_publiees` et `mention` (champs ajoutés) ; `par_type` et `par_nature` ne couvrent que les catégories publiées. Coût par étudiant : null avec `mention` (champ ajouté à chaque valeur nationale et régionale) quand le budget ou l'effectif manque ; de 2007 à 2014, il n'est plus publié à 0. ANR : un organisme, une catégorie ou une région sans aucune aide publiée (2005-2009) ou sans projet coordonné (investissements d'avenir et France 2030) a un montant null, pas 0 ; ordre : montants null en dernier. Lycées : une année dont toutes les lignes sont sans montant a `total_eur`, `nommes_eur` et `non_nommes_eur` null ; `lignes_sans_annee.montant_eur` null quand aucune ligne ; `controles[].lignes_total_absent` compte les totaux publiés absents. Un 0 calculé sur des montants publiés (par exemple aucun bénéficiaire non nommé une année) reste 0.

**Règles propres.** Une valeur absente à la source reste null ; un 0 publié reste 0 et il est compté (`lignes_montant_zero` : campagne 2017-2018 des Pays de la Loire, publiée à 0). Deux sources ne sont jamais additionnées. **Licences** : jeux de l'ANR, du Centre-Val de Loire et des Pays de la Loire sous ODbL 1.0 (mention du producteur, partage à l'identique des bases dérivées) ; les autres sous Licence Ouverte 2.0 ; chaque fichier porte `licence`. Ordre écrit dans `ordre`. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.35 Fonction publique : `fonction_publique/` (pipeline/fonction_publique.py)

Producteur : `pipeline/fonction_publique.py`. Sources (domaine `fonction_publique` de `collecte/catalogue.json`, entrepôt `data/lake/fonction_publique/`) : Insee, effectifs par versant, statut, ministère et type d'employeur 2011 à 2024 (Siasp), Insee Première n° 2094, TCRD 052 (régions et départements, fin 2023) ; jaunes « Personnels affectés dans les cabinets ministériels » (PLF 2025 et 2026) et « Recours aux conseils extérieurs » (PLF 2024 à 2026), en PDF sur le miroir de l'Assemblée nationale ; barème de la DGCL des indemnités de fonction des élus locaux (PDF). Commandes : `python collecte/collecte.py --domaine fonction_publique` (réseau, aucun refus contourné), `python pipeline/fonction_publique.py produire` (sans réseau). Tests : `pytest tests/test_fonction_publique.py`.

```
data/lake/fonction_publique/ (3 classeurs Insee, 6 PDF) ─┐
data/lake/etat/etat_etpt_lfi_2023.parquet (ministère)   ─┼─> pipeline/fonction_publique.py ─> site/data/fonction_publique/*.json
site/data/effectifs/<programme>.json, arbre/racine.json ─┘        (openpyxl, pdfplumber : mots positionnés, comme operateurs.py)
```

Tous les fichiers portent `millesime`, `source` (titre et URL de chaque document) et `collecte_le` (date de collecte de l'entrepôt, `pipeline/reproductible.py`).

| Fichier | Schéma | Contenu | Unité |
|---|---|---|---|
| `index.json` | `fonction_publique_index.schema.json` | `fichiers[]` `{fichier, contenu}`, `reperes` (effectifs, budget de l'État, cabinets, conseils, barème), `regles[]` (pas de double compte), `ecarts_entre_sources[]`, `recherche_prealable[]`, `limites[]` | divers |
| `effectifs_series.json` | `fonction_publique_effectifs_series.schema.json` | `series[]` `{cle, annee, revisee}` (2020 à 2023 en deux versions : publiée puis recalculée par l'Insee, clé suffixée `r`) ; `lignes[]` `{id, libelle, niveau, parent, valeurs.<statut>[], non_disponible[]}` avec `niveau` = `versant`, `type_employeur`, `ministere`, `detail_ministere` ou `ensemble` | milliers de personnes au 31 décembre |
| `emploi.json` | `fonction_publique_emploi.schema.json` | `tableaux.<figure>` `{titre, unite, colonnes[], lignes[] {rubrique, libelle, valeurs[], absences}, notes_source[]}` : effectifs et équivalents temps plein avec et sans contrats aidés, évolutions, caractéristiques, part des femmes, entrées et sorties, statut et type d'employeur | milliers ou % (par tableau) |
| `territoires.json` | `fonction_publique_territoires.schema.json` | `departements.<code>`, `regions.<code>`, `ensembles.<clé>` `{libelle, valeurs[7]}` dans l'ordre de `colonnes` (hors militaires) | milliers, %, pour 100 habitants ou emplois |
| `ministeres.json` | `fonction_publique_ministeres.schema.json` | `ministeres[]` `{id, ministere, programmes[], nb_programmes, etpt, titre2_eur, programmes_sans_titre2[], conseils_ae_eur, poles_cabinets, groupe_insee}` ; `programmes[]` `{programme, libelle, etpt, titre2_eur, fichier_effectifs, fichier_arbre, noeud_arbre, conseils_ae_consommees_eur}` ; `programmes_sans_ministere[]` ; `groupes_insee[]` ; `conseils_hors_nomenclature` ; `totaux` | ETPT, euros, milliers de personnes |
| `cabinets.json` | `fonction_publique_cabinets.schema.json` | `situations[]` (une par jaune) `{annee, date_situation, total, nb_cabinets, par_fonction, par_position_statutaire, poles[], edition, source}` ; `poles[]` `{pole, nb_cabinets, effectif_total, membres_cabinet, fonctions_support, dotation_isp_eur, ministeres_budget[]}` | effectifs physiques, euros |
| `conseils.json` | `fonction_publique_conseils.schema.json` | `totaux[]` (AE et CP par exercice, valeur de chaque édition), `par_ministere.<exercice>`, `par_mission`, `par_programme[]` `{programme, libelle, exercices.<AAAA> {ae_consommees_eur, ae_ouvertes_lfi_eur, part_pct, edition}}`, `controle_programmes`, `prestataires.<période>` | euros (AE) ; prestataires en M€ |
| `indemnites_elus.json` | `fonction_publique_indemnites_elus.schema.json` | `indice_brut_1027_mensuel_eur`, `lignes[]` `{annexe, collectivite, fonction, strate, taux_pct_ib1027, indemnite_brute_mensuelle_eur, base_legale}` | euros bruts par mois (plafond légal) |
| `remunerations.json` | `fonction_publique_remunerations.schema.json` | `salaires` (Insee, 2024) : `fonction_publique` `{brut_eur, net_eur, *_evolution_courants_pct, *_evolution_constants_pct}`, `versants[]` `{id (fpe, fpt, fph), ensemble, lignes[] (statuts, employeurs, filières), categories_fonctionnaires[] {categorie, part_eqtp_pct, brut_eur, traitement_brut_eur, primes_et_remunerations_annexes_eur, cotisations_csg_crds_eur, net_eur, net_evolution_constants_pct, part_primes_dans_brut_pct, deciles_net_eur}, deciles_net_eur, serie_net_euros_constants {euros_constants_de, annees[]}, tableaux}` ; `salaires_dgafp` (2023) : `moyennes_nettes[]` `{population, net_eur.{fpe,fpt,fph,fonction_publique}}`, `decomposition_fonctionnaires[]` `{categorie, elements[] {id, libelle, valeurs, non_publie}}`, `distribution_nette[]` ; `remuneration_salaries_apu` : `sur_100_eur` `{annee, valeurs[] {producteur, valeur_eur, statut, formule}}`, `eurostat.annees[]`, `dgafp` (séries 1978 à N) ; `reperes_budget_etat` ; `ecarts_entre_sources[]` | euros par mois en EQTP ; millions (Eurostat) ou milliards (DGAFP) d'euros ; € sur 100 € |

Pas de double compte (`ministeres.json`, `regles[]`) : un programme appartient à un seul ministère (jeu des ETPT de la LFI 2023) ; `etpt` et `titre2_eur` sont repris de `effectifs/<programme>.json`, jamais recalculés, et le total d'un ministère est la somme de ses programmes ; les effectifs de l'Insee (personnes au 31 décembre) et les ETPT (plafond d'emplois voté) sont posés côte à côte, jamais additionnés ; les établissements publics administratifs relèvent de `operateurs/` ; les cabinets sont déjà compris dans les effectifs des ministères ; les dépenses de conseil ne s'ajoutent pas à la masse salariale. `groupes_insee[]` rapproche les groupes de ministères de l'Insee des ministères du budget : rapprochement du projet d'après les intitulés (chaque ministère dans un seul groupe), à lire en ordre de grandeur. `poles_cabinets` et `ministeres_budget` sont des repères, sans montant reporté.

Personnes : aucune personne physique. Cabinets : agrégats par pôle ministériel, les lignes par cabinet du jaune (un ministre désigné par sa fonction) ne sont pas reprises. Prestataires de conseil : `denomination`, `siren`, `categorie_juridique` seulement si le jaune publie un SIREN et une catégorie juridique de personne morale (`sirene.personne_morale`) ; sinon `null` avec `motif_non_nomme`, le montant restant publié ; les listes détaillées de prestations ne sont pas lues. Barème des élus : fonctions et strates, aucun élu ni montant versé.

Valeurs absentes : `null`, jamais 0. `non_disponible[]` (séries, « nd »), `absences` (tableaux, « /// »), « / » des jaunes (aucune dépense publiée). Écarts entre sources : `index.json`, `ecarts_entre_sources[]` (deux publications de l'Insee sur l'effectif total ; champ avec ou sans militaires) et `conseils.json`, `totaux[].editions` (valeur de chaque édition du jaune) : publiés côte à côte, sans arbitrage ni addition.

Contrôles de lecture (bloquants à la production) : somme des versants = ensemble ; somme des pôles de cabinets = total général du jaune, colonne par colonne ; somme des ministères et des missions = total du jaune à l'arrondi près ; `controle_programmes` compare le total publié et la somme des programmes lus ; chaque rangée du barème vérifie montant = taux x indice brut 1027 (sinon écartée et comptée dans `rangees_ecartees`). Limites : cabinets et conseils sans jeu de données structuré depuis le PLF 2018 (PDF) ; édition PLF 2024 du jaune « conseils » limitée aux totaux (détail semestriel) ; collectivités à statut particulier absentes du barème ; `pipeline/tout.py` et `pipeline/entrees_lac.json` ne connaissent pas encore cette étape.

**Rémunérations (`remunerations.json`, ajout du 18/11/2026).** Sources : Insee Première n° 2100, 2101 et 2102 (salaires 2024 de l'État, de la territoriale et de l'hospitalière, classeurs des figures), DGAFP rapport annuel 2025, archive `ra_2025-remu_niveaux.zip` (salaires 2023 ; dépenses de personnel des administrations en comptabilité nationale, 1978 à 2024), Eurostat `gov_10a_exp` (D1 et TE par sous-secteur, France, depuis 1995) ; entrées `fp_insee_ip2100`, `fp_insee_ip2101`, `fp_insee_ip2102`, `fp_dgafp_ra2025_remu_niveaux`, `fp_eurostat_d1_apu` du catalogue. Commande seule : `python pipeline/fonction_publique.py remunerations`.

Ce que la page peut afficher : (1) salaire net et brut moyen par mois en équivalent temps plein, par versant (`salaires.versants[].ensemble`) et pour toute la fonction publique (`salaires.fonction_publique`), avec l'évolution sur un an en euros courants et constants ; (2) par catégorie A, B, C des fonctionnaires de chaque versant (`categories_fonctionnaires[]`) : part des effectifs, brut, traitement, primes, prélèvements, net, déciles ; pour l'ensemble de la fonction publique par catégorie, seule la DGAFP publie (`salaires_dgafp`, 2023) ; (3) distribution (`deciles_net_eur`, `salaires_dgafp.distribution_nette`) ; (4) série du salaire net moyen en euros constants depuis 2010 ou 2011 (`serie_net_euros_constants`) ; (5) **sur 100 € de dépense de toutes les administrations publiques**, la part qui rémunère leurs salariés (`remuneration_salaries_apu.sur_100_eur`, aussi dans `index.json`, `reperes.remunerations`) : deux valeurs côte à côte, Eurostat (`statut = "calculé"`, avec `formule`) et DGAFP (`statut = "publié"`), jamais arbitrées ; répartition de cette masse entre administration centrale, locale et sécurité sociale (`eurostat.annees[].repartition_remuneration_pct`, calculée) ; (6) `reperes_budget_etat` : titre 2 du budget de l'État et rémunération des salariés de l'État en comptabilité nationale, posés côte à côte.

Règles : salaires moyens par agent (sans cotisations des employeurs) et rémunération des salariés des comptes nationaux (masse, cotisations des employeurs comprises, militaires compris) ne se combinent jamais ; Insee 2024 et DGAFP 2023 ne sont pas comparés ; les dépenses des sous-secteurs ne s'additionnent pas (consolidation). Contrôles bloquants : net moyen identique entre figure 4 et tableau complémentaire 5, moyenne des déciles égale au net moyen, série en euros constants terminée sur la moyenne de l'année, ensemble de la fonction publique identique dans les trois publications, brut moins prélèvements égal au net (DGAFP), somme des D1 des sous-secteurs égale au total (Eurostat). Personnes : moyennes et déciles agrégés seulement ; les hautes rémunérations nominatives ne sont pas lues. Valeurs absentes : null (« /// » ou valeur publiée pour un seul versant, `non_publie`). Évolution du rapport interdécile en points. Écarts publiés dans `remunerations.json` (`ecarts_entre_sources`), pas dans `index.json`. Insee Melodi DD_CNA_APU non retenu (total des dépenses incohérent, voir `limites`).

### 2.36 Collectivités d'outre-mer : `outremer/` (pipeline/outremer.py)

Complète « Près de chez moi » (2.15, 101 départements) pour les six territoires que `local/` ne couvre pas : Saint-Pierre-et-Miquelon (975), Saint-Barthélemy (977), Saint-Martin (978), Wallis-et-Futuna (986), Polynésie française (987), Nouvelle-Calédonie (988). `pipeline/local.py` et `site/data/local/` ne sont pas modifiés. Commandes : `python pipeline/outremer.py collecter` (réseau, par `collecte/collecte.py`, entrée `outremer` de `collecte/catalogue.json` ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/outremer.py produire` (sans réseau, reproductible). Tests : `pytest tests/test_outremer.py`.

```
data/lake/outremer/outremer/ (geo.api.gouv.fr ; OFGL dotations-communes, dotations-gfp, dotations-departements ;
                              data.gouv.nc budget, EPA, EPIC, impôts ; Cour des comptes 2018-2020 ; DPT Outre-mer PLF 2026)
     └─> pipeline/outremer.py ─> site/data/outremer/index.json, <code>.json (six territoires), 988_budget.json
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `outremer/index.json` | `outremer_index` | `territoires[]` (code, nom, statut juridique, monnaie, population, `blocs.<bloc>` = statut), `blocs`, `statuts`, `parite_xpf`, `ecarts[]`, `credits_etat_plf2026` (territoires lus, contrôle), `limites`, `sources` (licence, verdict, date de collecte), `sources_inaccessibles[]`, `recherche_publique` |
| `outremer/<code>.json` | `outremer_territoire` | `territoire`, `blocs` (statut, source ou motif), `communes.<insee>` (nom, population ; `siren` et `epci` null : non publiés par l'API), `dotations_communes` (mêmes clés que `local/dotations/communes` : `communes.<insee>.eur.<annee>.<cle>`, plus `dgf_dacom`, `dpel` ; `recettes_reelles_fonctionnement_n_moins_2`), `dotations_intercommunalites` (`epci.<siren>`, 987), `dotations_collectivite` (clés de `local/dotations/departements`, 975 et 978), `credits_etat` (`cour_des_comptes_2018_2020` ; `dpt_plf2026` : `total_general`, `missions[].programmes[]`, six `colonnes`), `budget_collectivite`, `budget_communes` |
| `outremer/988_budget.json` | `outremer_budget_nc` | Nouvelle-Calédonie : `collectivite.totaux.<annee>.<budget>.<sens>.<section>` (`total`, `hors_ordre_et_reports`), `collectivite.chapitres.<annee>[]` (budget, sens, section, chapitre, libellé, nature, montants), `etablissements.<sigle>` (EPA, EPIC), `impots` (titres émis par impôt, 2010 à 2025) |

**Statut des blocs.** Chaque bloc porte `statut` : `publié` (avec sa `source`) ou `non publié en données ouvertes` (avec son `motif`). Un bloc absent des sources ouvertes (budget des communes des six territoires, budget de la Polynésie française, de Saint-Barthélemy, de Saint-Pierre-et-Miquelon, de Saint-Martin et de Wallis-et-Futuna, dotations sans ligne dans les jeux de l'OFGL) n'est jamais vide ni estimé : le statut décrit l'état de la publication, pas l'usage de l'argent. Une valeur absente à la source est `null`, jamais 0.

**Francs CFP.** Les montants de la Nouvelle-Calédonie sont publiés deux fois : montant d'origine (`devise_source` = `"XPF"`, colonnes `*_xpf`) et montant en euros (colonnes `*_eur`) à la parité fixe 1 € = 119,33174 XPF, arrondi à l'euro (`parite.xpf_par_eur`). Les dotations notifiées par la DGCL et les crédits de l'État sont en euros à la source, y compris pour 986, 987 et 988.

**Crédits de l'État.** Deux sources de périmètres différents, jamais raccordées ni additionnées : Cour des comptes (lois de finances initiales et exécution 2018 à 2020, AE et CP, population 2018, CP exécutés par habitant ; licence ODbL, déclarée dans le fichier et dans `sources`) et document de politique transversale Outre-mer du PLF 2026 (exécution 2024, LFI 2025, PLF 2026, par mission et programme ; les codes à quatre chiffres sont des prélèvements sur recettes). Le tableau du document de politique transversale est lu dans le PDF par position des mots et n'est publié que si la somme des programmes retrouve chaque mission et la somme des missions le total général, pour les six colonnes, à l'arrondi de la source près (1 € par ligne additionnée) ; sinon le bloc passe à `non publié en données ouvertes` avec le motif. `ecarts[]` (`source`/`montant` contre `autre_source`/`autre_montant`, `ecart`, `ecart_pct`, `lecture_ecart`) compare le prélèvement sur recettes au titre de la DGF du document (programme 3101, exécution 2024 et LFI 2025) à la DGF notifiée publiée par l'OFGL (communes, intercommunalités, collectivité) : un écart nul recoupe les deux sources.

**Budget de la Nouvelle-Calédonie.** Trois budgets jamais additionnés : `01` budget principal, `02` budget annexe de reversement, `03` budget annexe de répartition (le jeu ne publie que le code ; libellés des documents budgétaires de la DBAF, `budgets_source`). `nature` d'un chapitre : `reel`, `ordre` (écritures entre sections ou patrimoniales) ou `report` (résultat reporté, chapitres 001 et 002) ; `hors_ordre_et_reports` = somme des chapitres `reel`. Le dernier exercice est en cours (`exercice_en_cours`, `situation_au`). **Règle personnes physiques** : les chapitres à sept chiffres (opérations individualisées, libellées au nom d'un projet ou d'une entreprise, parfois individuelle) sont agrégés sous leurs trois premiers chiffres, sans libellé (`chapitres_individualises_agreges`) ; articles et sous-fonctions ne sont pas lus ; aucune personne n'est nommée. Établissements publics : sigle publié par la source.


### 2.37 Satellites locaux : `local_satellites/` (pipeline/local_satellites.py)

Pour chaque commune (code Insee), par département : les syndicats, le CCAS ou le CIAS, l'autorité organisatrice de la mobilité (AOM) et les services d'eau et d'assainissement qui la concernent, leurs dépenses (total, et par habitant quand une population est publiée), le taux de versement mobilité et le prix de l'eau. Commandes : `python pipeline/local_satellites.py collecter` (réseau ; un refus 401/403/429 est noté, jamais contourné ; la lecture des archives SISPEA demande `py7zr` et `xlrd`), `python pipeline/local_satellites.py produire` (sans réseau). Tests : `pytest tests/test_local_satellites.py`.

```
data/lake/collectivites/local_satellites/ (OFGL syndicats et CCAS-CIAS par exercice ; BANATIC ; Cerema AOM ;
    Urssaf table_taux_vmrr ; SISPEA 2024 ; extraits/ : colonnes en liste blanche, siège et catégorie SIRENE)
site/data/local/geo/, local/index.json (lecture seule)
     └─> pipeline/local_satellites.py ─> site/data/local_satellites/index.json, syndicats/<dep>.json,
                                         ccas/<dep>.json, mobilite/<dep>.json, eau/<dep>.json
                                           └─ liens `comptes` (vue + fichier) vers local/budgets/ et syndicats/
```

| Fichier | Schéma | Contenu | Source |
|---|---|---|---|
| `local_satellites/index.json` | `local_satellites_index` | `communes.<insee>` = masque de bits sur `blocs` ; `competences[]` (libellés BANATIC) ; `totaux` par exercice et catégorie (sommes non consolidées) ; `flux_croises[]` ; `hors_departement` ; `ecarts` ; `non_nommes` ; `sources[]`, `sources_inaccessibles[]`, `recherche_publique` | pipeline |
| `local_satellites/syndicats/<dep>.json` | `local_satellites_syndicats` | `communes.<insee>` = `[siren, via]` (`commune`, `epci`, `syndicat`) ; `syndicats.<siren>` : nom, nature (SIVU, SIVOM, SMF, SMO, PETR, POLEM), catégorie OFGL, compétences (indices), population BANATIC, `serie.<clé>[]` alignée sur `annees` (2018 à 2025), `eur_hab` ; `organismes_departementaux[]` (MDPH) ; `non_rattaches[]` (`absent_de_banatic`, `membres_hors_communes`) | OFGL `ofgl-base-syndicats`, BANATIC |
| `local_satellites/ccas/<dep>.json` | `local_satellites_ccas` | `communes.<insee>` = SIREN des centres ; `centres.<siren>` : type (`ccas`, `cias`), commune du siège, `rattachement`, `competence_cias_banatic`, population, `serie`, `eur_hab` | OFGL `ofgl-base-ccas-cias`, SIRENE, BANATIC |
| `local_satellites/mobilite/<dep>.json` | `local_satellites_mobilite` | `communes.<insee>` = `[aom, taux_vm, taux_vma, taux_vmr, date_debut, syndicat_sru, periode_suivante]` (taux en % de la masse salariale, en vigueur au 1er janvier 2026) ; `aom.<siren>` : nom, forme, population, `comptes` (lien), `versement_mobilite_eur[]` pour un syndicat | Cerema, Urssaf (ODbL) |
| `local_satellites/eau/<dep>.json` | `local_satellites_eau` | `communes.<insee>` = `[collectivité, rattachement]` ; `collectivites.<siren>` : nom, type, `comptes` (lien), `services[]` ; `services.<id>` = compétence, entité de gestion, mode de gestion, statut de l'opérateur, missions, population desservie, prix TTC au m³ (120 m³), état de la saisie | SISPEA 2024 (OFB), BANATIC |

**Pas de double compte.** Aucune dépense d'un satellite n'est ajoutée au budget d'une commune, d'une intercommunalité (2.15) ou d'un autre satellite. `flux_croises[]` décrit chaque flux (`de`, `vers`, `nature`, `deja_publie`, `ici`, `regle`) : contributions des membres aux syndicats (déjà dans les dépenses de fonctionnement des communes et intercommunalités ; côté syndicat, agrégat « Subventions reçues et participations »), adhésions entre syndicats, flux entre budgets d'un même organisme (non retirés : chaque montant est la somme des budgets publiés, `budgets` en donne le nombre), subvention de la commune au CCAS (agrégat « Participations des communes »), AOM dont le budget est déjà publié (`comptes` = lien, jamais un montant recopié), versement mobilité (taux, jamais converti en montant par commune), services d'eau (redevances des abonnés sur budget annexe : SISPEA ne publie pas de dépenses). Les `totaux` de l'index sont des sommes non consolidées, déclarées comme telles, qui ne s'ajoutent ni entre elles ni aux budgets locaux.

**Rattachement.** Syndicats : membres BANATIC ; `via` = `commune` (la commune est membre), `epci` (son intercommunalité est membre), `syndicat` (un syndicat dont elle ou son intercommunalité est membre est lui-même membre) ; une intercommunalité peut n'adhérer que pour une partie de ses communes, ce que l'export ne publie pas. CCAS : commune de l'établissement siège dans SIRENE (arrondissements de Paris, Lyon et Marseille ramenés à la commune) ; CIAS : communes de l'intercommunalité de la commune siège (CC, CA, CU ; métropole seulement si BANATIC indique la compétence). Eau : la commune est rattachée à la collectivité organisatrice (commune, intercommunalité, syndicat dont elle ou son intercommunalité est membre), jamais à une entité de gestion précise, SISPEA ne publiant pas les communes de chaque entité. Un organisme sans commune rattachée reste publié (`non_rattaches`, ou `hors_departement` dans l'index).

**Valeurs.** Montants en euros entiers (somme en centimes, arithmétique entière). `null` = non publié à la source (exercice absent, prix non saisi, taux sans ligne en vigueur), jamais 0. `eur_hab` : dépenses totales hors remboursements du dernier exercice publié (2024 ou 2025) divisées par la population publiée (BANATIC pour un syndicat, `local/geo/` pour un centre), `null` sinon. Écart entre le taux de l'Urssaf et la colonne du Cerema : compté dans `ecarts`, jamais tranché.

**Confidentialité.** Colonnes d'adresse, de courriel, de téléphone et de président (BANATIC, Cerema, SISPEA) jamais lues (listes blanches). Un organisme n'est nommé que si sa catégorie juridique SIRENE est celle d'une personne morale (`nom` null sinon, compté dans `non_nommes`). Le nom de l'opérateur d'un service d'eau n'est pas repris (aucun SIREN publié) ; le nom de l'entité de gestion passe par `local.objet_publiable`.

**Licences.** Licence Ouverte 2.0, sauf `mobilite/<dep>.json`, base dérivée de données sous ODbL 1.0 (Urssaf, Cerema) : chaque fichier porte `licence`, `licence_url`, `mention` et `partage_a_l_identique` ; l'index le rappelle dans `licences.mobilite`.


### 2.38 Contrôle et recouvrement : `recouvrement/` (pipeline/recouvrement.py)

Ce que les administrations notifient après contrôle, ce qu'elles encaissent, et ce que des organismes estiment. Trois notions séparées dans tous les fichiers, chacune avec producteur, périmètre, méthode et année : **notifié** (droits rappelés et pénalités de la DGFiP, redressements des Urssaf), **encaissé** (sommes payées dans l'année à la suite de contrôles), **estimation** (ordre de grandeur calculé par un organisme). S'y ajoutent les **restitutions** aux cotisants, publiées à côté des redressements, les créances retirées des comptes de l'État (**apurement**) et les **taux d'impayés**. Agrégats publiés seulement : aucun contribuable, aucun cotisant. Commandes : `python collecte/collecte.py recouvrement_urssaf_controle recouvrement_urssaf_travail_dissimule recouvrement_urssaf_impayes_national recouvrement_urssaf_impayes_regions recouvrement_urssaf_lexique recouvrement_etat_apurements recouvrement_etat_plan_comptable recouvrement_dgfip_annuaires recouvrement_documents recouvrement_ce_ecart_tva` (réseau ; un refus 403/429 est noté, jamais contourné), `python pipeline/recouvrement.py produire [--sortie DOSSIER]` (sans réseau ; `xlrd` et `pdfplumber` requis ; échoue si une citation n'est plus dans le document collecté ou si un tableau n'a plus la forme attendue). Tests : `pytest tests/test_recouvrement.py`.

```
data/lake/recouvrement/ (Urssaf : contrôle, travail dissimulé, taux d'impayés, lexique ; comptabilité générale de l'État ;
                         annuaires DGFiP 2010 et 2019 ; DPT fraude fiscale PLF 2026, HCFiPS, Cour des comptes ; page VAT gap)
     └─> pipeline/recouvrement.py ─> site/data/recouvrement/index.json, controle_fiscal.json, controle_urssaf.json,
                                      impayes.json, apurements_etat.json, estimations.json
```

| Fichier | Schéma | Contenu | Unité | Millésime |
|---|---|---|---|---|
| `recouvrement/index.json` | `recouvrement_index` | `notions` (libellé, définition), `regles[]`, `spheres`, `vues[]` (par producteur : `notifie[]`, `encaisse[]`, `restitution[]`, `estimation[]`, chaque montant avec `fichier` et `serie` ou `id` ; une liste vide a sa `*_note`), `fichiers[]`, `reperes`, `sources[]` (titre, producteur, url, licence, document collecté), `sources_inaccessibles[]`, `confidentialite`, `limites[]`, `verification_documents`, `recherche_publique` (verdict, licence, date) | divers | |
| `recouvrement/controle_fiscal.json` | `recouvrement_controle_fiscal` | DGFiP : `series[]` (`id` = `annuaire_<série>` ou `dpt_<série>`, `notion` = `notifie`, `encaisse` ou `activite`, `groupe`, `annees`, `valeurs`), `ruptures[]`, `notes_sources`, `raccord_editions_2010`, `ecarts_entre_sources[]` et `lecture_ecart`, `coherence`, `taux_recouvrement` (repris de la source, avec `citation`), `plaintes` (par procédé, par secteur) | M€, nombre | annuaires 1996 à 2019 ; document de politique transversale 2016 à 2024 |
| `recouvrement/controle_urssaf.json` | `recouvrement_controle_urssaf` | Urssaf : `controle` (`types[]` et `total` : `nombre_actions`, `nombre_regularisations`, `redressements_eur`, `restitutions_eur`, `regularisations_eur`, `part_restitutions_pct` ; `identite_regularisations`), `travail_dissimule` (`types[]`, `total`), `regle`, `definitions[]` (citations du lexique de l'Urssaf), `organismes[]` (26 Urssaf et caisses d'outre-mer, ordre alphabétique écrit dans `ordre`) | €, nombre | 2018 à 2024 |
| `recouvrement/impayes.json` | `recouvrement_impayes` | taux d'impayés des cotisations (entreprises de 10 salariés ou plus) : `national` et `regions[]`, séries `fin_mois`, `fin_mois_suivant`, `a_90_jours` alignées sur `mois` (`AAAA-MM`) | % des cotisations dues | janvier 2004 au dernier mois publié |
| `recouvrement/apurements_etat.json` | `recouvrement_apurements_etat` | comptes de l'État : `comptes[]` (`compte`, `libelle_source` du plan comptable, `categorie` = `admission_en_non_valeur` ou `decision_gracieuse`, `champ`, `montants_eur` alignés sur `annees`) | € | 2016 à 2025 |
| `recouvrement/estimations.json` | `recouvrement_estimations` | `estimations[]` (`sphere`, `objet`, `producteur`, `publication`, `annee_publication`, `annee_donnees` ou `annee_donnees_note`, `perimetre`, `methode`, `valeur` ou `valeur_basse`/`valeur_haute`, `unite`, `repere`, `citation`, `source` : url, page, document), `estimation_ensemble_fraude_fiscale` (`valeur` : null, constats cités), `constats[]` (Cour des comptes, HCFiPS : `texte` du site et `citation` exacte), `securite_sociale_detecte_recouvre` (ordres de grandeur du HCFiPS, `notion` = `notifie` ou `encaisse`, `precision`), `verification_documents` | Md€, M€ | publications 2024 et 2025 |

| Champ | Sens |
|---|---|
| `notion` | `notifie`, `encaisse`, `estimation`, `restitution`, `apurement`, `taux_impayes`, `activite` (nombre d'opérations) ; une série ne porte qu'une notion |
| `sphere` | `fiscale` (impôts, DGFiP et douane) ou `sociale` (cotisations et prestations) ; un fichier de montants, une vue ou une estimation n'a qu'une sphère |
| `series[].source` (contrôle fiscal) | `annuaires` (édition 2010 pour 1996 à 2009, édition 2019 pour 2010 à 2019) ou `dpt_2026` ; les deux sources couvrent 2016 à 2019 avec des périmètres différents : les deux séries sont publiées, `ecarts_entre_sources[]` donne `valeur`, `autre_valeur`, `ecart` et, pour le total des droits, `credits_non_rembourses_dpt` |
| `coherence` | écart maximal entre un total publié et la somme de ses composantes (arrondis de la source) |
| `citation` | texte exact de la source, retrouvé mot pour mot dans le document collecté à chaque production (`verification_documents`) ; jamais contrôlé par le lexique neutre, qui s'applique aux textes rédigés par le pipeline |
| `null` | valeur absente à la source (ligne sans montant, taux à 90 jours des derniers mois, année hors série), jamais 0 ; un 0 est un 0 publié (encaissements du STDR depuis 2020) |

**Règles propres.** Aucun total ni rapport entre la sphère fiscale et la sphère sociale ; aucune somme d'estimations (`estimation_ensemble_fraude_fiscale.valeur` vaut null : la Cour des comptes relève l'absence d'estimation d'ensemble, citée telle quelle). Aucun rapport encaissé / notifié n'est calculé : les encaissements d'une année portent sur des contrôles de plusieurs années ; seul le taux de recouvrement publié par la DGFiP est repris. Les restitutions figurent partout où figurent les redressements des Urssaf (mêmes années, même unité). Ordres écrits dans `ordre` : organismes et régions par ordre alphabétique, estimations par sphère, année de publication, identifiant. Sources inaccessibles (`index.json`) : classeur de tableaux de l'écart de TVA de la Commission européenne (429), encaissements des Urssaf après contrôle (non publiés en données ouvertes).

### 2.39 Justice et défense : `justice_defense/` (pipeline/justice_defense.py)

Établissements pénitentiaires (capacité, personnes détenues, densité : agrégats publiés, aucun individu), budget de la justice, juridictions et ressorts, exportations d'armement. Uniquement des documents publiés, déclarés dans `collecte/catalogue.json` (entrées `justice_defense_*`) ; rien de classifié. Commandes : `python pipeline/justice_defense.py collecter` (réseau, par `collecte/collecte.py` ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/justice_defense.py produire [--sortie DOSSIER]` (sans réseau, environ 2 min 30 ; lit `site/data/realisations/` en lecture seule). Tests : `pytest tests/test_justice_defense.py`.

```
data/lake/justice_defense/ (106 classeurs mensuels xlsx de la population écrouée ; table des ressorts et liste des
                            juridictions ; chiffres clés de la Justice 2026 ; rapport au Parlement 2025 sur les exportations
                            d'armement ; classeur des effectifs de la défense, sans donnée)
site/data/realisations/107.json (dépense constatée du programme 107) et <programme>.json (libellés)
     └─> pipeline/justice_defense.py ─> site/data/justice_defense/index.json, prisons.json, budget_justice.json,
                                        ressorts.json, armement.json (chacun < 5 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `justice_defense/index.json` | `justice_defense_index` | `fichiers[]`, `reperes` (dernier état de chaque fichier), `effectifs_defense` (statut `donnee_absente_a_la_source`, constat daté, empreinte du fichier, `a_relire` si l'empreinte change), `limites`, `sources[]` (page, licence, date de collecte), `sources_inaccessibles[]`, `recherche_publique` (verdict, licence, date) |
| `justice_defense/prisons.json` | `justice_defense_prisons` | `date_reference`, `national`, `etablissements[]` (une ligne par établissement et type de quartier : `disp`, `capacite_norme`, `capacite_operationnelle`, `detenus`, `densite_pct`, `historique_1er_janvier[]`, `montant_calcule_eur`), `montant_calcule` (formule, périmètre, limites), `serie_nationale[]` (mensuelle, avec `metropole` et `outre_mer`), `controles`, `couverture` (mois absents, doublons, classeurs non reconnus, URL de chaque classeur) |
| `justice_defense/budget_justice.json` | `justice_defense_budget_justice` | `budget` (crédits de paiement, dépenses de personnel, autorisations d'engagement, `programmes[]` 166, 107, 182, 101, 310, 335 en M€ et en part), `frais_de_justice` (total, civile et commerciale, pénale), `aide_juridictionnelle` (dépenses effectives, montants versés aux avocats), `ecarts[]` avec `realisations/107.json` |
| `justice_defense/ressorts.json` | `justice_defense_ressorts` | `juridictions[]` (`type`, `numero`, `nom`, `commune_insee`, `departement`), `types[]`, `par_departement`, `communes` (lignes alignées sur `colonnes` : code Insee puis identifiant de juridiction compétente), tables d'identifiants (`tribunaux_proximite`, `conseils_prudhommes`, et `cours_appel`, `tribunaux_judiciaires` quand ils sont repris), `coherence_source` |
| `justice_defense/armement.json` | `justice_defense_armement` | `prises_de_commandes`, `livraisons` (M€ courants) et `licences` (nombre) : `annees`, `pays[]` (`pays`, `region`, `valeurs[]`, `total`), `regions[]`, `hors_region[]` (« Multi-pays », « Divers »), `total_general`, `controles` ; `licences_par_categorie` (ML1 à ML22, AMA1 à AMA4 : `licences`, `montant_eur`, total) |

**Montant par établissement : calculé, pas publié.** `realisations/107.json` ne contient aucun indicateur de montant par journée de détention. Le site calcule donc : montant par journée = dépense constatée du programme 107 de l'année / (moyenne des personnes détenues au 1er de chaque mois publié × nombre de jours de l'année) ; `montant_calcule_eur` d'une ligne = montant par journée × moyenne de ses personnes détenues aux mêmes dates × nombre de jours. `montant_calcule.statut` vaut toujours `calculé` ; formule, périmètre (toute la dépense du programme, y compris milieu ouvert et immobilier), méthode (prorata uniforme) et limites sont dans le fichier. Le site doit afficher ce montant avec la mention « calculé » et sa formule, jamais comme une valeur de l'administration.

**Ressorts : colonnes reprises seulement si cohérentes.** À chaque production, le siège de la juridiction indiquée pour une commune est comparé au département de la commune (`coherence_source.colonnes`). Une colonne dont plus de 5 % des communes renvoient à un autre département n'est pas reprise (`colonnes_non_reprises`, `constat`) : c'est le cas, dans le fichier publié en mai 2026, du tribunal judiciaire et de la cour d'appel (publiés ensemble). `colonnes` donne donc la liste réelle des colonnes de `communes` ; les tables `cours_appel` et `tribunaux_judiciaires` sont absentes tant que ces colonnes ne sont pas reprises. Colonnes de voie, code postal, coordonnées, téléphone et courriel : jamais lues. Aucune commune n'est attribuée aux établissements pénitentiaires (absents du jeu ; un rapprochement par le nom a été écarté après essai).

**Règles propres.** Un tiret ou une cellule vide à la source reste `null`, jamais 0 ; « 0,0 » du rapport sur l'armement (moins de 50 000 €) reste 0. Un total publié qui ne retombe pas sur la somme de ses lignes est publié avec son écart (`controles.ecarts_totaux_directions`, `controles.ecarts_regions`, `ecarts[]` : `source`/`montant` contre `autre_source`/`autre_montant`), jamais corrigé ; en revanche la production s'arrête si un tableau relu dans un PDF ne retombe plus sur son total général (somme des programmes = crédits de paiement, régions + hors région = total général, catégories = total des licences). Prises de commandes, livraisons et licences ne s'additionnent pas. Seuls les classeurs xlsx de la population écrouée sont lus (juillet 2014 à mars 2019, puis depuis janvier 2023) ; le détail par établissement vaut pour le format publié depuis 2023. Ordres écrits dans `ordre`. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.40 Retraites par régime : `retraites/` (pipeline/retraites.py)

Retraités, nouveaux retraités, pensions moyennes par régime et par année (2004 à 2024), cotisants quand ils sont publiés, ressources par origine du compte d'affectation spéciale Pensions, crédits de l'État aux régimes spéciaux. Agrégats publiés seulement. Les montants de pensions par régime restent dans `prestations/` (2.24) et les dépenses des organismes dans `secu/` (2.16) : cette vue y renvoie par des liens, sans les recopier. Commandes : `python pipeline/retraites.py collecter` (réseau ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/retraites.py produire` (sans réseau). Tests : `pytest tests/test_retraites.py`.

```
data/lake/secu/retraites_* (DREES EACR table A-Cadrage ; DREES emploi intérieur 2004-2016 ; cubes du Service des
                            retraites de l'État ; PLF 2025 recettes des CAS et dépenses selon destination ;
                            Caisse des dépôts CNRACL et Ircantec ; MSA retraités du régime agricole)
     └─> pipeline/retraites.py ─> site/data/retraites/index.json, regimes.json, etat.json
                                    └─ liens (fichier + id) vers secu/cps/, secu/arbre/, arbre/ (programmes 195, 197, 198), prestations/
```

| Fichier, champ | Sens |
|---|---|
| `regimes.json`, `regimes.<id>` | une entrée par caisse de l'EACR (`code_caisse`, `libelle_source`, `type` : `base`, `complementaire`, `integre`, `ensemble` ou null) ; séries par année (clés chaînes) : `retraites_droit_direct`, `retraites_droit_derive`, `retraites_tous_droits`, `nouveaux_retraites_droit_direct` (personnes au 31 décembre), `pension_droit_direct_eur_mois`, `pension_totale_eur_mois`, `pension_droit_derive_eur_mois` (montants de décembre, euros par mois), `source_eacr` (millésime de l'enquête ou du modèle) |
| `regimes.<id>.cotisants` | seulement quand un jeu ouvert existe (`tous_regimes` : emploi intérieur DREES 2004-2016 ; `cnracl` : actifs 2014-2022 ; `ircantec` : cotisants 2014-2021) : `source`, `definition`, `valeurs`, rapport cotisants / retraités (publié par la DREES, ou calculé avec `rapport_methode`) |
| `regimes.<id>.zeros_source` | séries et années où la source donne une pension moyenne égale à 0 : publiées null |
| `index.json`, `regimes[].liens[]` | `vue` (`secu_cps`, `secu_arbre`, `arbre_etat`, `prestations`), `fichier`, `id`, `md`, `lecture`, `partage_avec` quand le nœud couvre plusieurs régimes : même argent vu d'une autre vue, jamais additionné |
| `index.json`, `ecarts[]` | `regime`, `annee`, `grandeur` (`effectif` ou `eur_mois`), `source`/`valeur` contre `autre_source`/`autre_valeur`, `ecart`, `ecart_pct`, `lecture_ecart` : cubes du Service des retraites de l'État et Caisse des dépôts contre EACR |
| `index.json`, `ecarts_msa` | sommes nationales des deux colonnes du fichier de la MSA, sous les libellés de la source, face aux effectifs de l'EACR ; `annees_colonnes_inversees` et `constat` : les deux colonnes changent de contenu d'une année à l'autre à la source, sans correction ici |
| `etat.json`, `cas_pensions` | PLF 2025 : `programmes[]` (741, 742, 743, crédits de paiement par action), `sections[]` (recettes par ligne, `origine`, `par_origine_eur`, `regimes`, `recettes_moins_depenses_eur`), `recettes_par_origine_eur` et `_pct` ; origines : `cotisations_salariales`, `contributions_employeurs`, `cotisations_salariales_et_patronales`, `contribution_fspoeie_ratocem`, `budget_general`, `transferts`, `autres` (règle de classement par libellé dans `origines`) |
| `etat.json`, `retraites_etat` | pensions de droit direct en paiement au 31 décembre (civils, militaires hors gendarmes, gendarmes), 2015 à 2025 : `effectif`, `pension_moyenne_eur_mois` |
| `etat.json`, `credits_regimes_speciaux` | programmes 195, 197, 198 par action : `execution_2024_eur` (nœud de `arbre/`, avec `fichier` et `id`), `plf_2025_cp_eur`, `regime` quand l'action nomme un régime de l'EACR (SNCF, RATP, marins, mines) ; deux millésimes côte à côte, pas un écart |

Règles propres : les effectifs des régimes ne s'additionnent pas (une personne qui perçoit des pensions de plusieurs régimes est comptée dans chacun ; seule la série `tous_regimes`, estimée par la DREES, compte chaque personne une fois) ; aucune masse de pensions n'est recalculée à partir d'un effectif et d'une moyenne ; une valeur absente à la source est null, jamais 0. Non couverts, faute de jeu ouvert (`sources_inaccessibles`) : cotisants des autres régimes, ressources par origine des régimes hors CAS Pensions, exécution du CAS Pensions ; les fichiers du Conseil d'orientation des retraites ne sont pas repris (réutilisation soumise à accord).

### 2.41 Rapports d'observations définitives des chambres régionales et territoriales, 2020 à 2026 : `controle/rod_crtc/` (pipeline/controle.py)

Métadonnées des rapports d'observations définitives publiés en ligne par les chambres régionales et territoriales des comptes du 1er janvier 2020 au 31 décembre 2026 : organisme contrôlé (personne morale), code commune ou SIREN quand il est identifiable, date, chambre, thèmes, liens vers ccomptes.fr. Ni texte des rapports, ni résumé, ni réponses des organismes. Aucun jeu ouvert ne donne ces métadonnées après 2019 (data.gouv.fr s'arrête aux rapports de 2019, déjà repris en 2.20 ; data.ccomptes.fr injoignable le 18/11/2026) : les pages de ccomptes.fr sont lues une par une. Commandes : `python pipeline/controle.py collecter --volets ccomptes,siren_rod --budget <s>` (réseau, reprenable ; au plus une requête par seconde vers chaque service, reprises comprises ; pages du plan du site modifiées depuis le 1er janvier 2020 lues d'abord, celles au nom d'un organisme en tête, puis les pages modifiées depuis leur lecture ; verrou contre deux collectes simultanées ; arrêt net au premier 403 ou 429, noté dans `controle/index.json` (`sources_inaccessibles`), jamais contourné ; robots.txt exclut les adresses à paramètres : recherche et listes filtrées ne sont pas utilisées), `python pipeline/controle.py produire` (sans réseau). Tests : `pytest tests/test_controle.py`.

```
ccomptes.fr/sitemap_publication/sitemap.xml + pages (1 requête/s) ─> data/lake/_cache/ccomptes/publications.jsonl
API Recherche d'entreprises (1 requête/s) ─────────────────────────> data/lake/_cache/controle_rod_siren.json
site/data/controle/rod_crtc/<année>.json (mémoire publiée) + site/data/local/geo (COG en vigueur)
     └─> pipeline/controle.py ─> site/data/controle/rod_crtc/index.json, <année>.json
                               └─> publications/collectivites/<dep>.json (mêmes rapports, rangés par département)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `controle/rod_crtc/<année>.json` (2020 à 2026) | `controle_rod_crtc_annee.schema.json` | `annee`, `comptes` (par chambre, par niveau), `rapports[]` triés par date décroissante puis identifiant |
| `controle/rod_crtc/index.json` | `controle_rod_crtc_index.schema.json` | `perimetre`, `regle_personnes`, `regles_rattachement`, `fichiers`, `comptes` (par année, chambre, niveau, type d'organisme ; codes commune et EPCI ; SIREN par méthode ; preuve de personne morale ; intitulés non publiés ; hors période ; repris de la mémoire publiée), `themes[]`, `pages_crtc_hors_rapports` (avis budgétaires, jugements : comptés, non listés), `couverture` (pages du plan du site, pages modifiées depuis 2020 lues et restantes, dernier passage de collecte) |

Un rapport : `id` (`cc-<n° de page>`), `titre` (intitulé publié), `organisme` (début du titre, parenthèses finales retirées), `organisme_type` (lu au début du nom : commune, communauté de communes, syndicat, établissement de santé, société, association... ; null s'il n'est pas reconnu), `personne_morale` (true, ou null si rien ne l'établit) et `personne_morale_preuve` (catégorie juridique SIRENE 2xxx à 9xxx, collectivité du code officiel géographique, ou type d'organisme lu dans le titre), `siren`, `siren_methode`, `categorie_juridique`, `niveau` et `codes` `{commune, epci, departement, region}` (code officiel géographique en vigueur) avec `rattachement[]` (méthodes appliquées, dans l'ordre), `date` (mise en ligne sur ccomptes.fr), `annee`, `date_communicabilite`, `date_envoi`, `juridiction` (forme publiée, par exemple « CRC ÎLE-DE-FRANCE »), `chambre` (« Chambre régionale des comptes Île-de-France »), `themes[]` (libellés complets de ccomptes.fr), `type`, `type_document` (intitulé du document quand ce n'est pas « Rapport d'observations définitives »), `url` (page), `url_document` (rapport), `url_synthese`, `source`.

Règles. Un rapport est une page d'une chambre (institution CRC, CTC ou CRTC) dont un document est un rapport d'observations définitives, ou de catégorie « Rapport » (gabarit des chambres territoriales) ; avis budgétaires, jugements et autres pages des chambres sont comptés, non listés. Département : parenthèse du titre (nom ou numéro), sinon commune unique de ce nom dans le ressort de la chambre, sinon nom d'un département du ressort cité dans le titre, sinon ressort d'un seul département ; une région n'a pas de département ; chambres des collectivités d'outre-mer hors code officiel géographique : aucun code. SIREN : communes et EPCI par le code officiel géographique ; autres organismes par l'API Recherche d'entreprises, retenu seulement si un seul résultat personne morale porte le même nom (normalisé, sigle retiré) avec son siège dans le département (départements : catégorie 7220 ; régions : 7230). `publications/collectivites/<dep>.json` (2.20) liste désormais les rapports d'observations définitives seulement : 2015 à 2019 par data.gouv.fr, 2020 à 2026 par ces pages, avec `organisme_type`, `themes` et `siren`.

**Personnes (bloquant).** Aucun résumé ni texte de rapport ; aucun ordonnateur, comptable, responsable ni auteur de réponse. Un intitulé où un nom de personne est possible (civilité suivie d'une capitale, prénom courant suivi d'un nom en capitales) est remplacé par « intitulé non publié (nom de personne possible) », sans organisme ni SIREN, et compté dans `intitules_non_publies`.

**Mémoire et couverture.** Les rapports déjà publiés restent publiés quand le cache de collecte ne les contient pas (passage à froid, cache purgé) ; une page relue les met à jour, une page en 404 les retire. Une page publiée en 2020 ou après a été modifiée au plus tôt le jour de sa publication : les pages du plan du site modifiées depuis le 1er janvier 2020 contiennent tous les rapports de la période. Les pages non lues ne sont pas publiées (aucune métadonnée devinée) ; `couverture` donne les pages lues et restantes, la collecte hebdomadaire reprend où la précédente s'est arrêtée.

### 2.42 Fraîcheur des données : `fraicheur/` (pipeline/fraicheur.py)

Pour chaque source lue par le site : date de dernière collecte, millésime publié, date de publication déclarée par la source, prochaine publication attendue et statut. Commandes : `python pipeline/fraicheur.py collecter` (réseau : métadonnées des sources de `pipeline/sources.json` seulement ; un refus 401/403/429/451 est noté, jamais contourné), `python pipeline/fraicheur.py produire [--sortie DOSSIER]` (sans réseau). Étape « fraicheur » de `pipeline/tout.py`, après toutes les étapes de données et avant le datapackage (un nouvel axe se déclare au-dessus d'elle). Tests : `pytest tests/test_fraicheur.py`. Écran : `/methode/fraicheur`.

```
collecte/catalogue.json, pipeline/sources.json, pipeline/entrees_lac.json ──┐
data/lake/manifest.json (collecte), data/raw/<id>.schema.json ──────────────┤
data/lake/_cache/fraicheur/verifications.json (collecter) ──────────────────┼─> pipeline/fraicheur.py ─> site/data/fraicheur/index.json
data/lake/_cache/tout/etat.json, site/data/mise_a_jour.json ────────────────┤
en-têtes de site/data/<page>/index.json, .github/workflows/data.yml ────────┘
```

| Champ | Sens |
|---|---|
| `date_reference` | dernière collecte de l'entrepôt (`pipeline/reproductible.py`) : les statuts sont établis à cette date |
| `sources[]` | une entrée par source : `pipeline/sources.json` (`origine` = `sources.json`), catalogue (`catalogue`), source lue par une étape hors catalogue (`lue_par_une_etape`), collecte d'un module tracée au manifeste (`module`) ; `etapes` = pages qui la lisent (relevé `pipeline/entrees_lac.json`, champs `module` et `lu_par`, titre du catalogue), liste vide si aucune page n'est rattachée |
| `derniere_collecte` | dernière collecte réussie ; `collecte_origine` : `manifeste`, `verification` (étape « base » : version utilisée identique à celle que publie la source) ou `page` (date de collecte publiée par l'index de la page) ; null si inconnue. `derniere_verification` : dernière tentative, réussie ou non |
| `millesime_publie` | millésime publié par la page pour cette source (`millesime_origine` = `source`) ou en-tête de la page qui la lit (`page`), avec `fichier_millesime` |
| `publication_source` | `{date, nature}` : modification du jeu déclarée par le portail (Opendatasoft), mise à jour du jeu ou du fichier sur data.gouv.fr, en-tête HTTP Last-Modified, champ « updated » d'Eurostat ; null si la source n'en déclare pas |
| `prochaine_publication` | `{date, edition, calendrier, passee}` pour la dernière édition collectée d'une publication récurrente rattachée à un calendrier officiel (`calendriers[]` : projet de loi de finances, loi organique relative aux lois de finances, art. 39 ; résultats de la gestion, art. 46 et 54 ; approbation des comptes de la sécurité sociale, code de la sécurité sociale, art. LO 111-6 ; notifications du déficit et de la dette, règlement (CE) n° 479/2009, art. 3 et 14) ; null sinon |
| `statut` | `a_jour`, `en_retard` (édition attendue avant la date de référence, ou version plus récente déclarée par la source), `inaccessible` (refus ou indisponibilité à la dernière collecte), `non_verifiee` (aucune collecte datée et réussie) ; définitions dans `statuts`, `explication` propre à chaque source |
| `etapes[]` | par page : `libelle` en langage courant (`titre` = titre technique de `pipeline/tout.py`), `statut_passage` (passage en cours s'il est plus récent que le rapport, sinon `mise_a_jour.json`), `millesime`, `par_statut`, `derniere_collecte`, `sources_inaccessibles_passage`, `signalements` (sources signalées par l'index de la page) |
| `mise_a_jour_hebdomadaire` | jour et heure lus dans `.github/workflows/data.yml`, relecture mensuelle de l'amont, budget de temps, étapes dans l'ordre |
| `non_collectables` | sources déclarées non collectables au catalogue, avec leur motif |

**Règles propres.** Un statut est un constat daté, jamais un jugement sur la source ou son producteur : « en retard » ne s'appuie que sur un calendrier fixé par un texte ou sur une version plus récente déclarée par la source elle-même ; sans calendrier connu, `prochaine_publication` vaut null. Une date inconnue est null, jamais estimée. Une erreur de collecte est résumée (code HTTP, délai, coupure) sans l'adresse de la requête. Les notes reprises du catalogue et des pages suivent le lexique neutre (`docs/lexique_neutre.json`, substitutions explicites `SUBSTITUTIONS`). Ordre écrit dans `ordre` (page, puis titre). Le rapport de passage est écrit après la dernière étape : une étape déjà passée dans le passage en cours prend son statut dans `data/lake/_cache/tout/etat.json`. Une nouvelle publication récurrente se rattache à son calendrier dans `FAMILLES` (pipeline/fraicheur.py). Deux productions sur les mêmes entrées sont identiques octet pour octet.

### 2.43 Solidarités des départements : `solidarites_departements/` (pipeline/solidarites_departements.py)

Ce que les départements versent au titre des allocations individuelles de solidarité (RSA, APA, PCH) d'après leurs comptes, les recettes que ces comptes rattachent à ces allocations (TICPE, FMDI, dotations de la CNSA), un reste à charge calculé par le site, et les bénéficiaires de l'aide sociale départementale publiés par la DREES (personnes âgées, personnes handicapées, enfance, RSA), par collectivité et par année. Agrégats publiés seulement, aucune personne nommée. Les dépenses par poste de l'enquête Aide sociale (RSA, APA, PCH, ASE, autres ; brutes et nettes) restent dans `territoires/` (2.25) et les foyers du RSA payés par les CAF dans `prestations/` (2.24) : cette vue y renvoie par des liens, sans les recopier, et publie les écarts. Commandes : `python pipeline/solidarites_departements.py collecter` (réseau, par `collecte/collecte.py` ; entrées `solidarites_*`, `local_departements` et `local_regions` de `collecte/catalogue.json` ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/solidarites_departements.py produire [--sortie DOSSIER]` (sans réseau ; lit `territoires/` et `prestations/` en lecture seule). Tests : `pytest tests/test_solidarites_departements.py`.

```
data/lake/collectivites/local_departements.parquet, local_regions.parquet (OFGL, comptes consolidés 2012-2025)
data/lake/solidarites_departements/ (DREES : bénéficiaires PA-PH et ASE, séries longues ; minima sociaux, tableau 11 ;
                                     OFGL : formules des agrégats)
site/data/territoires/ (dépenses DREES par poste), site/data/prestations/ (foyers du RSA des CAF, RSA recentralisé)
     └─> pipeline/solidarites_departements.py ─> site/data/solidarites_departements/index.json, comptes.json,
                                                 beneficiaires.json, ecarts.json (chacun < 1 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `solidarites_departements/index.json` | `solidarites_departements_index` | `presentation` ; `departements[]` (code de `local/geo`, collectivités à lire dans `comptes` et `beneficiaires`, lien vers `territoires/<dep>.json`) ; `collectivites[]` (périmètres) ; `totaux.<annee>` (somme des collectivités par colonne et nombre de collectivités, `reste_a_charge_calcule` : `montant_eur`, `allocations_eur`, `recettes_eur`, `part_couverte_pct`, `collectivites`) ; `reste_a_charge` (statut `calculé`, producteur, formules, périmètre, méthode, limites) ; `ecarts[]` nationaux ; `ecarts_departements` (renvoi) ; `rsa_recentralise` ; `liens` ; `methode` ; `limites` ; `sources` (verdict, licence, `entrepot`, `collecte_le`) ; `sources_inaccessibles` ; `recherche_publique` |
| `solidarites_departements/comptes.json` | `solidarites_departements_comptes` | `colonnes` = `allocations_rsa`, `allocations_apa`, `allocations_pch`, `frais_hebergement`, `ticpe`, `fmdi`, `cnsa` ; `roles` (`allocation`, `depense`, `recette`) ; `definitions`, `libelles_ofgl`, `formules_ofgl` (formule publiée par l'OFGL, par nomenclature M52 ou M57 et par exercice) ; `collectivites.<code>` : `nom`, `departements`, `sirens`, `population.<annee>`, `eur.<annee>` et `eur_hab.<annee>` alignés sur `colonnes`, `reste_a_charge_calcule_eur.<annee>` aligné sur `colonnes_reste_a_charge` (`rsa`, `apa_pch`), `financeur_rsa.<annee>` (`departement`, `etat`, `departement_puis_etat`) pour un département dont le RSA est recentralisé, `perimetre` |
| `solidarites_departements/beneficiaires.json` | `solidarites_departements_beneficiaires` | `series[]` (`id`, `groupe`, `libelle`, `definition`, `titre_source`, `source`, `onglet`, `champ`, `annees`, `rupture`, `marques_source`) ; `collectivites.<code>.valeurs.<serie>` (nombres alignés sur les années de la série), `perimetre`, `rsa_2016_ancien_systeme` ; `totaux.<france, metropole, drom>.<serie>` (totaux estimés publiés par la DREES, jamais recalculés) |
| `solidarites_departements/ecarts.json` | `solidarites_departements_ecarts` | `lignes` alignées sur `colonnes` = `grandeur`, `code`, `annee`, `valeur`, `autre_valeur`, `ecart`, `ecart_pct` ; `grandeurs.<grandeur>` : `source`, `autre_source`, `lecture_ecart`, nombre de lignes ; `sources_ecarts` |

Collectivités : codes de la DREES. `67` et `68` (Bas-Rhin et Haut-Rhin jusqu'en 2020 : le code `67A` de l'OFGL porte alors deux lignes par exercice, lues par SIREN) puis `6AE` (Collectivité européenne d'Alsace, depuis 2021) ; `69` (Rhône jusqu'en 2014), `69D` et `69M` (Nouveau Rhône et Métropole de Lyon, depuis 2015) ; `2A` et `2B` jusqu'en 2017 puis `20R` (Collectivité de Corse) ; `972` et `973` : département jusqu'en 2015 puis collectivité territoriale unique (base des régions de l'OFGL) ; `75` : département de Paris puis Ville de Paris (2019). `departements[]` dit, pour chaque département du site, quelles collectivités lire ; une collectivité unique figure pour deux départements, à ne pas additionner. Dans `beneficiaires.json`, la DREES publie aussi la Corse (`20R`) avant 2018 et `67`, `68` après 2021 : `perimetre` le précise.

**Reste à charge : calculé, pas publié.** Aucun reste à charge par département n'est publié en données ouvertes par l'administration. Le site calcule `rsa` = `allocations_rsa` - `ticpe` - `fmdi` et `apa_pch` = `allocations_apa` + `allocations_pch` - `cnsa`, null dès qu'une composante est absente de la source, quand l'État finance le RSA (premier exercice entier après la recentralisation : 973 et 976 depuis 2019, 974 depuis 2020, 93 et 66 depuis 2022, 09 depuis 2023) ou pour le RSA d'une collectivité unique (TICPE régionale et départementale confondues). Limites publiées dans le fichier : les dotations de la CNSA comprennent d'autres concours que l'APA et la PCH, la TICPE compense aussi d'autres transferts de compétences, le dispositif de compensation péréquée et les fonds de péréquation ne sont pas isolés dans les comptes publiés. Le site doit afficher ce montant avec la mention « calculé », sa formule et ses limites, jamais comme une valeur de l'administration.

Règles propres : une valeur absente de la source (agrégat non publié pour l'exercice, cellule vide, « - ») reste null, jamais 0 ; un 0 publié reste 0. Deux sources ne sont jamais additionnées : `ecarts.json` publie, par collectivité de même périmètre, les comptes (OFGL) face aux dépenses brutes de l'enquête Aide sociale (DREES, lues dans `territoires/`) pour l'APA, la PCH avec l'ACTP et l'allocation du RSA, les bénéficiaires de l'APA à domicile et de la PCH payés en décembre selon deux publications de la DREES, et les allocataires du RSA (DREES, CAF et MSA) face aux foyers payés par les CAF (`prestations/`) ; `index.json` publie l'écart national (comptes hors Mayotte face au total estimé de la DREES). Non couverts (`sources_inaccessibles`) : concours de la CNSA par département (cnsa.fr refusé par la vérification TLS, documents PDF ou Word), notes de répartition du FMDI, du dispositif de compensation péréquée et du fonds de péréquation des droits de mutation (PDF, dont une image numérisée), données provisoires 2025 de la DREES. Ordres écrits dans `ordre`. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.44 Fonds européens structurels et d'investissement : `fonds_europeens/` (pipeline/fonds_europeens.py)

Ce que l'Union européenne finance en France par ses fonds structurels et d'investissement, avec les cofinancements nationaux : FEDER, FSE (2014-2020) et FSE+ (2021-2027), Initiative pour l'emploi des jeunes (IEJ), Fonds pour une transition juste (FTJ), FEADER (développement rural), FEAMP et FEAMPA ; Facilité pour la reprise et la résilience (FRR) telle que publiée par Eurostat. Par programme, région, fonds, thème et année ; listes d'opérations publiées par six autorités de gestion. Ce que la France verse au budget de l'UE, les retours par rubrique et les bénéficiaires nommés de Kohesio, du FTS et d'Horizon Europe restent dans `ue/` (2.17) : cet axe y renvoie par des liens (`liens[]`), sans les recopier ni les additionner. Commandes : `python pipeline/fonds_europeens.py collecter` (réseau, par `collecte/collecte.py` sur les entrées `fe_*` de `collecte/catalogue.json` ; un refus 401/403/429 ou une page anti-robot est noté, jamais contourné ; puis rapprochement SIRENE local), `python pipeline/fonds_europeens.py resoudre` (sans réseau : rapprochement seul, environ 2 min), `python pipeline/fonds_europeens.py produire [--sortie DOSSIER]` (sans réseau, environ 30 s, sorties reproductibles octet pour octet). Tests : `pytest tests/test_fonds_europeens.py`.

```
cohesiondata.ec.europa.eu (API SODA, filtre France, CC0) : e4v6-qrrq, 99js-gm52, gayr-92qh, rmer-4wcy (2014-2020) ;
   hgyj-gyin, 3git-md5z, pbbz-hmfu, 9qee-iv7c (2021-2027) ; 7wr2-9vpr, vvmb-dsbj (FEADER, plan stratégique PAC) ;
   f5vn-zy5i (référentiel des programmes) ; métadonnées des jeux     -> data/lake/europe/fe_cohesion_*
Eurostat gov_rrf_fa, gov_rrf_use (France, CC BY 4.0)                   -> data/lake/europe/fe_eurostat_frr_*
listes d'opérations : Bretagne, Pays de la Loire, Normandie 2021-2027, Île-de-France 2014-2020 et 2021-2027,
   La Réunion 2014-2020 (data.gouv.fr, portails régionaux)              -> data/lake/_restreint/europe/fe_ops_*
stock SIRENE des unités légales (pipeline/local.py)                     -> data/lake/_cache/local/
     └─> pipeline/fonds_europeens.py ─> site/data/fonds_europeens/index.json, programmes.json, regions.json,
                                        themes.json, annees.json, frr.json, operations.json, operations/<liste>.json
                                        (cache : data/lake/_cache/fonds_europeens/rapprochement.json)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `fonds_europeens/index.json` | `fonds_europeens_index` | `periodes` (`2014-2020`, `2021-2027`, `2023-2027`), `fonds[]` (`code`, `libelle`, `code_source`), `definitions`, `perimetre` (fonds retenus, `hors_perimetre[]` avec montant et raison, Interreg, FEADER, FRR), `totaux[]` par période (`par_fonds`, `total`, `date_execution`, `annee_paiements`), `feader_psp_2023_2027`, `frr` et `operations` (résumés et liens), `ecarts[]`, `fichiers[]`, `liens[]` vers `ue/`, `sources[]` (jeu, licence, mise à jour publiée, date de collecte), `sources_inaccessibles[]`, `recherche_publique` (verdict, licence, date), `limites[]`, `confidentialite`, `ordre`, `verification` (licences publiées par cohesiondata, programmes non rattachés) |
| `fonds_europeens/programmes.json` | `fonds_europeens_programmes` | un programme par ligne : `cci`, `periode`, `titre` (intitulé court de la Commission), `portee` (`régional`, `national`, `interrégional`), `region` (code Insee) et `groupe`, `territoire` (région d'avant 2016 citée par l'intitulé), `fonds[]`, `total` et `par_fonds` (blocs), `execution` (`date_reference`, `prevu_total_eur` du même jeu), `paiements` (`annee`, `prevu_ue_eur`, `prefinancement_net_eur`, `paiements_intermediaires_nets_eur`, `total_net_eur`) |
| `fonds_europeens/regions.json` | `fonds_europeens_regions` | 18 régions (codes Insee depuis 2016), Saint-Martin (`977`, collectivité d'outre-mer), groupes `national` et `interregional` : `programmes[]`, `periodes[]` (`par_fonds`, `total`, `annees[]` : `decide_cumule_eur`, `depense_cumulee_eur`, `paye_ue_cumule_eur`) |
| `fonds_europeens/themes.json` | `fonds_europeens_themes` | 2014-2020 : `themes[]` par objectif thématique (1 à 13, `TA` assistance technique, `MULTI` publié à l'exécution seulement) et `mesures_feader[]` (M01 à M23) ; 2021-2027 : `themes[]` par objectif stratégique (1 à 5, 8 = FTJ) avec `objectifs_specifiques[]` (RSO, ESO, JSO, MSO), `domaines_intervention[]` (code et `libelle_source` de la Commission, par fonds, `operations` déclarées) |
| `fonds_europeens/annees.json` | `fonds_europeens_annees` | par période : `engagements_ue` (crédits d'engagement annuels des plans financiers, par fonds), `paiements_ue` (cumuls par fonds et total, `annuel_*` = différence de deux cumuls, `annee_partielle`), `execution` (décidé et dépensé cumulés par fonds et par année) ; `frr` (fonds reçus par année, lien) |
| `fonds_europeens/frr.json` | `fonds_europeens_frr` | Eurostat : `fonds_recus` (`total_eur`, `subventions_eur`, `prets_eur`, `dont_paiements_anticipes_eur`, `pct_pib`, `cumul_eur` calculé), `emplois.categories[]` (`TOTAL`, dépenses courantes `CUR`, en capital `CAP` dont `P51G` formation brute de capital fixe, `D9` transferts en capital), `liens[]` (`ue/contribution.json`, `ue/beneficiaires/index.json`, `numerique_etat/fonds/france_relance.json`) |
| `fonds_europeens/operations.json` | `fonds_europeens_operations_index` | `listes[]` (`id`, `fichier`, autorité de gestion, région, périodes, fonds, opérations, opérations nommées, `part_cout_nommee`, url, licence, date de collecte), `couverture` (programmes régionaux de la politique de cohésion couverts), `rapprochement` (méthode, date du stock SIRENE, intitulés retirés), `liens[]`, `sources_inaccessibles[]` |
| `fonds_europeens/operations/<liste>.json` | `fonds_europeens_operations` | `colonnes` puis `operations[]` (lignes alignées : `id`, `periode`, `fonds`, `annee_debut`, `date_fin`, `siren`, `denomination` SIRENE, `categorie_juridique`, `intitule`, `departement`, `commune_insee`, `theme` publié, `cout_total_eur`, `montant_ue_eur`, `hors_ue_eur`, `taux_ue` ; Pays de la Loire : `etat_eur`, `region_eur`, `departement_eur`, `prives_eur`, `autofinancement_eur` en plus), `montant_ue_mode`, `non_nommes[]` (agrégats par période, fonds, année et `motif`), `motifs`, `totaux[]`, `comparaison_commission[]`, `controles`, `ordre` |

| Champ | Sens |
|---|---|
| bloc (`par_fonds`, `total`) | `prevu_ue_eur`, `prevu_national_eur`, `prevu_total_eur`, `decide_eur`, `depense_eur`, `paye_ue_eur` ; `null` = grandeur non publiée par la source (jamais 0) ; les blocs `themes` n'ont pas `paye_ue_eur` |
| prévu | plan financier du programme, dernière version adoptée. 2014-2020 : part UE et cofinancement national (public et privé) publiés ; 2021-2027 : `prevu_national_eur` = total prévu - part UE (calcul du projet), un fonds compté dans une seule dimension de la catégorisation (domaine d'intervention, type d'intervention pour le FEAMPA) |
| décidé, dépensé | coût éligible total des opérations sélectionnées et dépenses éligibles déclarées, cumulés à la dernière transmission (`date_reference` : date du rapport 2014-2020, cycle `AAAA-MM` 2021-2027) ; publiés en coût total seulement, sans part UE ; le décidé peut dépasser le prévu (écart publié tel quel dans `ecarts[]`) |
| payé UE | paiements nets de la Commission (préfinancements et paiements intermédiaires, moins les recouvrements), cumulés depuis le début de la période ; la dernière année est partielle |
| `engagements_ue` | crédits d'engagement de l'Union par année budgétaire (2014-2020 : dotation principale + réserve de performance ; 2021-2027 : `y2021` à `y2027`) |
| périodes | `2014-2020` (y compris REACT-EU, objectif thématique 13, et les années 2021-2022 du FEADER), `2021-2027`, `2023-2027` = FEADER du plan stratégique PAC (part UE prévue et paiements seulement) |
| `feader_psp_2023_2027` | part UE du FEADER (`7wr2-9vpr`) et, côte à côte sans addition, les financements nationaux obligatoire et additionnel publiés pour l'ensemble du plan stratégique PAC (`vvmb-dsbj`, FEAGA et FEADER) ; aucun paiement direct ni aide individuelle n'est repris |
| `ecarts[]` | `source`/`montant_eur` contre `autre_source`/`autre_montant_eur`, `ecart_eur`, `lecture_ecart` : prévu UE de deux jeux de la Commission, décidé et prévu, FEADER 2023-2027 de deux jeux ; jamais tranchés |
| `comparaison_commission[]` | coût total d'une liste d'opérations contre le décidé transmis à la Commission pour le même programme et le même fonds, `ecart_pct`, `lecture_ecart` (dates et périmètres différents) |
| `montant_ue_mode` | `publié` (Pays de la Loire, Normandie, La Réunion) ou `calculé` = coût × taux publié (Bretagne, Île-de-France) |

**Rattachement territorial.** Programme rattaché à une région par son intitulé (table `MOTIFS_REGIONS`, vérifiée par les tests) ; les programmes 2014-2020 des régions d'avant 2016 sont rattachés à la région actuelle qui les contient (`territoire` garde la région citée) ; « Guadeloupe et St Martin » va à la Guadeloupe ; portée « National » du référentiel de la Commission : groupe `national` ; programmes interrégionaux (massifs, fleuves) : groupe `interregional`, jamais répartis. Un programme sans rattachement apparaît dans `verification.programmes_non_rattaches` (vide aujourd'hui). Les programmes Interreg (code pays `TC`) ne sont pas ventilés par pays dans la source et ne sont pas repris ; AMIF, BMVI et ISF (fonds des affaires intérieures) et le FEAD 2014-2020 sont publiés dans `perimetre.hors_perimetre` avec leur montant et leur raison, hors totaux.

**Personnes physiques (bloquant).** Aucune liste de bénéficiaires du FEADER ni des aides de la PAC n'est collectée ; aucun agriculteur ni entrepreneur individuel n'est nommé. Dans les listes d'opérations, un bénéficiaire est nommé seulement si sa catégorie juridique SIRENE est celle d'une personne morale (`sirene.personne_morale`), sous sa dénomination SIRENE (jamais le nom brut de la source) : par le SIRET publié (Pays de la Loire), sinon par rapprochement du nom avec le stock SIRENE local (mots du nom triés, même règle que `pipeline/ue.py`, une seule unité légale de catégorie 2xxx à 9xxx ; plusieurs unités : `ambigu`). Un nom qui peut désigner une personne (prénom fréquent, civilité : `local.contient_nom_de_personne`) n'est jamais rapproché. Les autres opérations sont agrégées par période, fonds, année et motif (`personne_physique`, `siren_inconnu`, `sans_nom`, `nom_de_personne_possible`, `non_rapproche`, `ambigu`), sans nom ni intitulé. Intitulé d'une opération nommée publié par `local.objet_publiable` (null s'il peut contenir un nom de personne). Colonnes d'adresse, de description longue, de coordonnées : jamais lues. Le cache de rapprochement ne contient que des empreintes sha256 des noms et des dénominations de personnes morales ; les listes brutes restent dans `data/lake/_restreint/`. Conservation testée : opérations nommées + agrégées = total publié de la liste.

**Neutralité.** Prévu, décidé, dépensé et payé sont publiés côte à côte, jamais additionnés ni rapportés l'un à l'autre en taux ; aucun classement par montant ; ordres écrits dans `ordre` (régions par code Insee, programmes par période, groupe et CCI, fonds dans l'ordre FEDER, FSE, FSE+, IEJ, FTJ, FEADER, FEAMP, FEAMPA, opérations par contribution de l'Union décroissante). Libellés français des objectifs et mesures rédigés par le projet, libellé de la Commission gardé dans `libelle_source` (anglais pour les objectifs spécifiques et les domaines d'intervention 2021-2027).

Sources inaccessibles (`sources_inaccessibles`) : Europe en France (europe-en-france.gouv.fr, page anti-robot, non contournée) et tableau de bord de la FRR de la Commission (application Qlik sans fichier). Règle n°0 : `recherche_publique` (cohesiondata et Eurostat réutilisables tels quels, listes régionales à adapter, dépôts publics en inspiration seulement). Dates par `pipeline/reproductible.py` et par la date de collecte du manifeste ; deux productions sur le même entrepôt donnent des fichiers identiques.

### 2.45 Aides aux entreprises : `aides_entreprises/` (pipeline/aides_entreprises.py)

Ce que les autorités publiques ont octroyé aux entreprises, dispositif par dispositif, chacun avec sa notion de montant : **registre européen de transparence des aides d'État** (Transparency Award Module de la Commission européenne : aides individuelles publiées par les autorités françaises, élément d'aide), **France 2030** (montants engagés à la décision), **France Relance** (participation de l'État annoncée aux projets industriels, Industrie du futur, chèque France Num), **prêts garantis par l'État** (principal des prêts garantis, pas une dépense). Montants par année, par dispositif, par secteur (section NAF) et par région ; écarts entre sources publiés, jamais additionnés ni départagés. Complète sans les recopier `controle/aides_entreprises.json` (2.20 : estimations publiées de l'ensemble des aides, exonérations Urssaf) et `beneficiaires/france2030.json` (2.9 : bénéficiaires nommés de France 2030). Commandes : `python pipeline/aides_entreprises.py collecter [--budget 1800] [--rafraichir]` (réseau, reprenable : sources du catalogue `aides_france2030_projets`, `benef_plan_de_relance`, `aides_relance_*`, `aides_pge`, `aides_pge_historique` par `collecte/collecte.py`, puis registre TAM mois par mois, puis répertoire SIRENE : stock partagé `data/lake/_cache/local/sirene_unite_legale.parquet`, à défaut API Recherche d'entreprises ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/aides_entreprises.py produire [--sortie DOSSIER]` (sans réseau ; lit `site/data/local/geo/`, `site/data/beneficiaires/france2030.json` et `site/data/controle/aides_entreprises.json` en lecture seule). Tests : `pytest tests/test_aides_entreprises.py`.

```
Commission européenne, recherche publique du registre TAM (pages de 100 résultats, par mois d'octroi, France)
     └─> data/lake/aides_entreprises/tam/fr_AAAA-MM.csv (sans nom de bénéficiaire), manifeste.json, secteurs_nace.json
data/lake/aides_entreprises/ (France 2030 ; France Relance, montants agrégés ; PGE Etalab au 1er janvier et au 31 décembre 2021)
data/lake/beneficiaires/benef_plan_de_relance.parquet (lauréats industriels de France Relance)
data/lake/_cache/aides_entreprises_sirene.json, recherche_entreprises.json (catégorie juridique, section NAF, dénomination
                                                                           des seules personnes morales)
site/data/local/geo/, beneficiaires/france2030.json, controle/aides_entreprises.json (lecture seule)
     └─> pipeline/aides_entreprises.py ─> site/data/aides_entreprises/index.json, tam.json, france2030.json,
                                          france_relance.json, pge.json (chacun < 5 Mo)
```

| Fichier | Schéma | Contenu | Unité | Millésime |
|---|---|---|---|---|
| `aides_entreprises/index.json` | `aides_entreprises_index` | `dispositifs[]` (`id`, `nom`, `notion` de montant, `fichier`, `annees`, `par_annee_eur`, `total_eur`, compte d'aides, de projets, de bénéficiaires ou de prêts), `par_annee.annees.<AAAA>.<dispositif>`, `par_secteur.sections.<A-U>.<dispositif>`, `par_region.regions.<code COG>.<dispositif>` (un montant par source, jamais additionnés, `regle` écrite), `ecarts[]`, `liens[]` (dont `prestations/index.json` : sommes versées aux ménages, même format), `confidentialite`, `limites[]`, `sources[]`, `sources_inaccessibles[]`, `recherche_publique` (verdict, licence, date), `fichiers[]` | € | registre consulté au … ; sources collectées au … |
| `aides_entreprises/tam.json` | `aides_entreprises_tam` | `definitions`, `total`, `par_annee`, `sans_date_octroi`, `par_mesure[]` (numéro `sa`, `titre`, `titres_differents`, `autorites` : trois premières), `par_objectif[]`, `par_instrument[]`, `par_type_beneficiaire[]`, `par_secteur[]` (section NAF et `divisions[]`), `par_region[]` (`code` COG ou `rattachement`), `rattachement_regions`, `par_tranche[]`, `croisements` (`annee_secteur`, `annee_region`, `annee_tranche`), `delai_publication_jours`, `non_rattaches`, `beneficiaires` (groupe de bénéficiaires 2.9 + `total_eur`, `top[].aides`, `top[].par_annee_eur`, `verification_classement`), `collecte` | € (élément d'aide) | aides octroyées depuis juillet 2016 |
| `aides_entreprises/france2030.json` | `aides_entreprises_france2030` | `total`, `composantes_eur` (subvention, avance remboursable, intérêts, écart au montant d'aide), `par_annee`, `par_operateur[]`, `par_region_financement[]`, `par_region_beneficiaire[]`, `par_secteur[]`, `par_typologie[]`, `par_objectif[]`, `par_strategie[]`, `par_programme[]` (424, 425), `croisements`, `couverture_secteur`, `rapprochement` (total de 2.9), `beneficiaires_nommes` (renvoi) | € (montant engagé) | projets décidés de 2021 à 2025 |
| `aides_entreprises/france_relance.json` | `aides_entreprises_france_relance` | `laureats` (`colonnes`, `lignes` : personnes morales nommées, sans montant ; `projets_agreges` par motif), `projets_par` (mesure, filière, type d'entreprise, région), `montants` (`par_mesure_et_filiere`, `par_mesure_et_type_entreprise`, `par_departement`, `par_region`, `par_mesure`, `totaux_participation_etat_eur`, `industrie_du_futur`, `cheque_france_num`), `ecarts[]` | € (participation de l'État, investissement) ; projets ; entreprises | lauréats 2021-2022 ; montants publiés en 2021 et 2022 |
| `aides_entreprises/pge.json` | `aides_entreprises_pge` | `dates`, `methode_par_annee`, `total`, `par_secteur[]`, `par_region[]`, `par_departement[]` : `situations.<date>` (`prets`, `montant_eur`) et `par_annee` (2020, 2021), `differences_negatives`, `ecarts[]` | € (principal garanti) ; prêts | situations au 1er janvier et au 31 décembre 2021 |

| Champ | Sens |
|---|---|
| `element_aide_eur` | registre TAM : somme des éléments d'aide publiés en montant exact (équivalent-subvention, montant total à l'octroi, même versé sur plusieurs années) ; `aides_avec_montant` les compte |
| `fourchettes` | aides publiées par tranche (avantages fiscaux) : `borne_basse_eur`, `borne_haute_eur` (null si une tranche est ouverte, « 30 000 001 € et plus ») ; jamais ajoutées à `element_aide_eur` |
| `montant_nominal_eur` | montant prêté, garanti ou avancé, quand l'autorité le publie (somme séparée) |
| `rattachement` (régions du registre) | `region`, `ancienne_region` (région d'avant 2016 rattachée à la région actuelle), `departement` (rattaché à sa région), `zone_pluriregionale` (zone NUTS 1, dont « Régions ultrapériphériques françaises » : non répartie), `national` (« France »), `hors_france` (bénéficiaire établi dans un autre État membre), `non_rattache` (libellé publié tel quel dans `non_rattaches`) |
| `section` | section de la NAF rév. 2 (A à U). Registre TAM : libellé NACE de l'aide, rattaché par la nomenclature de la recherche publique (NACE rév. 2 de 2008 et rév. 2.1 de 2025 : une division garde son numéro, la section est celle de ce numéro ; section seule de la rév. 2.1 rattachée à la section de même contenu). France 2030 : activité principale de l'unité légale dans SIRENE (« non résolue » sinon, publiée avec son montant). PGE : section publiée (« Z » non connu : `section` null) |
| `beneficiaires.verification_classement` | `seuil_eur` (montant du 50e nommé), `non_verifies_au_dessus_du_seuil` : le classement nommé n'est complet (`classement_complet`) que si ce nombre est nul |
| `par_annee` (PGE) | 2020 = situation au 1er janvier 2021 (premiers prêts en mars 2020) ; 2021 = différence entre les situations du 31 décembre et du 1er janvier 2021 ; une différence négative (annulation, reclassement) est publiée telle quelle dans `differences_negatives` |
| `ecarts[]` | `objet`, `source`/`montant_eur` contre `autre_source`/`autre_montant_eur`, `ecart_eur`, `ecart_pct`, `lecture_ecart` (constat, jamais tranché) ; `citation` et `autre_url` pour une publication citée, `autre_fichier` et `autre_id` pour une estimation de `controle/aides_entreprises.json` |

**Personnes (bloquant).** Le nom du bénéficiaire publié par le registre n'est jamais lu ni enregistré (l'entrepôt ne garde que l'identifiant national). Une personne morale (catégorie juridique `2xxx` à `9xxx`, `sirene.personne_morale`) est nommée d'après SIRENE ; entrepreneurs individuels, exploitants agricoles, groupements de personnes physiques, identifiants absents : agrégés (`exclus_personnes_physiques_ou_non_identifies`) ; SIREN non vérifiés : `autres_non_verifies`. Les colonnes de nom et de prénom du stock SIRENE ne sont jamais lues. France Relance : lauréats nommés sous la même règle, sans description de projet ni adresse. France 2030 : aucun nom ici (2.9). Textes saisis par les autorités (intitulés de mesure, noms d'autorités) : `local.objet_publiable` (null s'ils peuvent contenir un nom de personne ; le numéro SA reste publié).

**Règles propres.** Quatre notions de montant (élément d'aide, montant engagé, participation annoncée, prêt garanti) : aucune somme entre dispositifs, `index.json` les publie côte à côte ; une même aide peut figurer dans deux sources (aide France 2030 de plus de 100 000 € aussi publiée dans le registre). Écarts publiés : tables France Relance entre elles (la table par territoire ne retombe pas sur les tables par mesure ; l'écart est publié avec un constat arithmétique, la source ne l'explique pas), fichiers PGE régional et départemental, PGE contre le chiffre arrondi de la Direction générale du Trésor, registre TAM contre les estimations « aides d'État au sens européen » de `controle/aides_entreprises.json`. Collecte du registre : pages publiques de résultats (100 par page, une requête par seconde au plus, tri par référence), par mois d'octroi ; un mois n'est écrit que complet ; `--rafraichir` relit les six derniers mois après 6 jours et les mois 7 à 18 après 30 jours (les autorités publient jusqu'à un an après l'octroi : années récentes incomplètes). null n'est jamais 0. Dates lues dans les manifestes de collecte (`SOURCE_DATE_EPOCH` prioritaire) : deux productions sur le même entrepôt sont identiques octet pour octet. Ordres écrits dans `ordre`. Sources inaccessibles (`index.json`) : export CSV/XLSX du registre (nom et courriel demandés, envoi par courriel : non utilisé), mention Covid-19 du registre (critère sans colonne), PGE de 2022 (non publiés), montant par lauréat de France Relance (non publié).

### 2.46 Logement : `logement/` (pipeline/logement.py)

Aides du logement, canal par canal, sans additionner les canaux : aides personnelles au logement (APL, ALF, ALS) par aide, par département et par année, avec le type de logement et le type de parc ; MaPrimeRénov' (dossiers validés par département, montants nationaux, exécution budgétaire) ; prêts à taux zéro et éco-prêts à taux zéro émis par année et par département ; aides à la pierre et programmes budgétaires 109, 135, 177 et 174 par des liens. Ce qui est déjà publié ailleurs n'est pas recopié : total des aides personnelles par département dans `prestations/` (2.24, même source CNAF), dépenses fiscales du logement (dont le crédit d'impôt accordé aux banques pour le PTZ, mesures 210313 et 210321) dans `niches/` (2.18), crédits des programmes dans `arbre/` et `realisations/`, Anah, FNAP, CGLLS et Ancols dans `operateurs/` (2.21), comparaison européenne dans `comparaison/fiches.json` (fiche `logement`). Commandes : `python pipeline/logement.py collecter` (réseau : sources `logement_*` de `collecte/catalogue.json` par `collecte/collecte.py`, base PTZ de 307 Mo copiée compressée en flux dans `data/lake/logement/ptz/` après contrôle `collecte/integrite.py` ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/logement.py produire [--sortie DOSSIER]` (sans réseau, environ 30 s ; lit `site/data/local/geo` pour les noms de départements, et en lecture seule `prestations/`, `niches/`, `arbre/`, `realisations/`, `operateurs/`, `comparaison/`). Tests : `pytest tests/test_logement.py`.

```
data/lake/logement/ (CNAF al_s_type_log_dep/nat, al_s_type_parc_dep/nat ; DITP baromètre IND-292 ; SDES MaPrimeRénov' 2024 ;
                     Sénat, rapport n° 743 (2024-2025) ; SGFGAS bases PTZ 1995-2021 et éco-PTZ 2009-2021)
     └─> pipeline/logement.py ─> site/data/logement/index.json, aides_personnelles/<annee>.json, maprimerenov.json, ptz.json
                                   └─ liens (fichier + id) vers prestations/, niches/, arbre/, realisations/, operateurs/, comparaison/
```

| Fichier | Schéma | Contenu | Unité | Millésime |
|---|---|---|---|---|
| `logement/index.json` | `logement_index` | `fichiers[]`, `aides_personnelles` (`annees`, `dernier_mois_publie`, `fichiers.<annee>`, série `france.<annee>` : `aides`, `type_parc`, `type_logement` en triplets, `controles.<annee>`, `mois_absents_a_la_source`), `maprimerenov` (repères : `dates_cumul`, `france_cumul`, `france_annee`, `execution_cp_total_meur`), `ptz` (repères de la dernière année, `renvois`), `aides_a_la_pierre` (`definition`, `liens`, `non_publie`), `programmes[]` (`code`, `role`, `nom`, `liens[]`), `operateurs[]`, `renvois[]`, `ecarts[]`, `sources`, `sources_inaccessibles[]`, `recherche_publique`, `limites`, `regles`, `confidentialite`, `collecte_le` | divers | |
| `logement/aides_personnelles/<annee>.json` | `logement_aides_personnelles` | une année : `departements.<code>` (101) et `hors_departements` (978, 99, XX) : `nom`, `aides` (`ensemble`, `apl`, `alf`, `als`), `type_logement` (`location`, `accession`, `foyer`, `inconnu`) et `type_parc` (`public`, `prive`), chacun décliné par aide ; `france` (jeux nationaux de la CNAF) ; `controles` ; `mois_absents_a_la_source` ; `renvoi_total` | foyers ; € ; € par foyer et par mois | 2017 à 2025 (années complètes) |
| `logement/maprimerenov.json` | `logement_maprimerenov` | `departements.<code>` : `cumul` (aligné sur `dates_cumul`), `annee` (aligné sur `annees_calculees`) ; `france` ; `controle_somme_departements` ; `national_sdes` (`etapes` : dépôts, engagés, demandes de solde, soldés ; `soldes` : nombre, montant des travaux, subvention MaPrimeRénov', montant moyen) ; `budget_etat` (tableau du Sénat : `lignes` par programme 174, 362, 135 et total, `controle_total`, `liens` vers `arbre/`) ; `limites` | dossiers ; € ; M€ (budget) | cumul décembre 2022 à juillet 2026 ; SDES 2020-2024 ; exécution 2022-2024 |
| `logement/ptz.json` | `logement_ptz` | `ptz` et `eco_ptz` : `france`, `par_type` (PTZ : `ancien`, `neuf` ; éco-PTZ : `type_1` à `type_5`), `departements.<code>`, `autres_territoires` (`20` : Corse de 1995 à 2005 ; `978`), `departement_non_renseigne` ; séries alignées sur `annees_ptz` ou `annees_eco_ptz` ; `renvois` vers les dépenses fiscales | prêts ; € | prêts émis 1995-2021 (PTZ), 2009-2021 (éco-PTZ) |

| Champ | Sens |
|---|---|
| triplet | `[foyers_decembre, montant_annuel_eur, montant_moyen_eur]` (`colonnes`) : foyers payés au titre de décembre ; somme des 12 montants mensuels versés par les CAF ; montant annuel / somme des foyers payés chaque mois (montant mensuel moyen par foyer). Décembre absent : triplet entièrement null ; un autre mois absent : montant annuel et moyen null |
| `ensemble` | colonne NDURAL de la CNAF ; `apl` + `alf` + `als` = `ensemble` à quelques unités près (`controles.aides_moins_ensemble`), un foyer perçoit au plus une aide ; les types de logement et de parc retombent sur l'ensemble (`controles.types_*_moins_ensemble`) |
| `renvoi_total` | `prestations/departements/<annee>.json`, clé `aides_logement` : même ensemble, mêmes foyers, montants à quelques euros près (autre jeu de la CNAF) ; null avant 2019 ; ne jamais additionner les deux vues |
| `france` / `controles.france_moins_somme_des_lignes` | France = jeux nationaux de la CNAF ; écart avec la somme des lignes départementales publié (mois absents à la source pour Mayotte, Saint-Martin et le code 99 en décembre 2020 à 2024 : le national les compte les autres mois) |
| `cumul` (MaPrimeRénov') | « Nombre de dossiers MaPrimeRénov' validés en cumul » (DITP, indicateur IND-292) aux dates de `dates_cumul` (décembre 2022 = valeur initiale publiée) ; `annee` = différence de deux cumuls de décembre, **calculée** par le site |
| `budget_etat.controle_total` | somme des programmes contre total publié par le Sénat : en 2022 le total publié (2 102 M€) ne retombe pas sur ses lignes (2 154 M€), l'écart de 52 M€ est publié sans correction |
| `departement_non_renseigne` (PTZ) | prêts sans département à la source (secret statistique de la SGFGAS), comptés dans `france` |
| `ecarts[]` (index) | `objet`, `annee`, `unite`, `source`/`montant` contre `autre_source`/`autre_montant`, `ecart`, `ecart_pct`, `lecture_ecart` : APL, ALF, ALS champ CAF contre dépenses tous régimes (vue des prestations) ; MaPrimeRénov' SDES (aides des dossiers soldés, par geste) contre crédits consommés (Sénat) ; dossiers validés (DITP, calculé) contre dossiers engagés (SDES) |
| liens | `vue` (`arbre_etat`, `realisations`, `depenses_fiscales_programmes`, `depenses_fiscales_mesures`, `operateurs`, `prestations`, `comparaison`), `fichier`, `id` ou `mesures[]` ou `programme`, `md` pour l'arbre (exécution 2024), `lecture` : même argent vu d'une autre vue, jamais additionné |

**Pour l'écran (à faire par un autre agent).** Une page « Logement » peut lire `logement/index.json` (repères et liens), puis `logement/aides_personnelles/<annee>.json` pour le département choisi (code de `local/geo`) : APL, ALF, ALS et leur ensemble en foyers et en euros, répartition location / accession / logement-foyer et parc public / privé. MaPrimeRénov' : nombre de dossiers validés du département (`maprimerenov.json`, `departements.<code>.cumul` et `annee`, statut « calculé » pour `annee`) ; les montants ne sont publiés qu'au niveau national (`national_sdes`, `budget_etat`) et l'écran doit le dire. PTZ : nombre et montant des prêts émis par année et par département, avec la mention qu'un prêt n'est pas une dépense de l'État et un lien vers la dépense fiscale (mesures 210313 et 210321 de `niches/mesures.json`). Aides à la pierre : liens vers l'action 135-01 de l'arbre et l'opérateur FNAP, avec la phrase de `aides_a_la_pierre.non_publie`. Chaque canal reste séparé (unités et sources différentes, `avertissement`) ; les écarts de `ecarts[]` se montrent tels quels.

**Règles propres.** Agrégats seulement ; les bases de prêts de la SGFGAS (une ligne par prêt, sans nom) ne sont lues que pour l'année, le type, le département et les montants (jamais commune, revenu, prix au m²) ; montant d'un département-année de moins de 5 prêts : null (le nombre reste publié). Absence à la source : null, jamais 0 (un code ou un type sans ligne une année, par exemple 2A et 2B avant 2005 codés 20 dans la base PTZ). Un code de département ou un type inconnu, un tableau du Sénat ou un classeur du SDES qui change de forme, une définition de l'indicateur IND-292 qui change : la production s'arrête. Lignes multiples d'un même département et d'un même mois (décembre 2020 à 2022 à la CNAF) additionnées, comme dans `prestations/`. Non couverts (`sources_inaccessibles`) : montants MaPrimeRénov' par département, logements sociaux financés et aides à la pierre par département, prêts émis depuis 2022, ressources du FNAL par financeur. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.47 Revenus et impôt sur le revenu par commune : `revenus_communes/` (pipeline/revenus_communes.py)

Pour chaque commune en vigueur (mêmes codes Insee que `local/geo/<dep>.json`) : nombre de foyers fiscaux, foyers imposés, revenu fiscal de référence (RFR) de tous les foyers et des foyers imposés, impôt net, pour chaque année publiée par la DGFiP (revenus 2002 à 2024, fichiers IRCOM 2003 à 2025), et par tranche de revenu fiscal de référence quand la DGFiP publie ce détail ; niveau de vie médian de l'Insee (médiane du revenu disponible par unité de consommation, Filosofi 2021 et Filosofi 2 2023). Agrégats publiés seulement. Commandes : `python pipeline/revenus_communes.py collecter` (réseau, par `collecte/collecte.py` : entrées `revenus_communes_ircom`, `revenus_communes_filosofi_2021`, `revenus_communes_passage_cog` et l'entrée existante `insee_ds_filosofi_cc` ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/revenus_communes.py produire [--sortie DOSSIER]` (sans réseau, environ 4 min ; lit `site/data/local/geo/` en lecture seule). Tests : `pytest tests/test_revenus_communes.py`.

```
data/lake/revenus_communes/ (IRCOM : une archive par année, classeurs départementaux, 370 Mo ; Filosofi 2021 ;
                             table de passage annuelle des communes 2026)
data/lake/comptes_nationaux/insee_ds_filosofi_cc.zip (Filosofi 2 2023)      site/data/local/geo/<dep>.json
     └─> pipeline/revenus_communes.py ─> site/data/revenus_communes/index.json, communes/<dep>.json,
                                          tranches/<annee>/<dep>.json (chacun < 1 Mo)
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `revenus_communes/index.json` | `revenus_communes_index` | `annees[]` (par année de revenus : `annee_imposition`, `ircom`, `url`, `geographie_source`, `rapprochement` avec `non_rattaches[]`, `unite_source`, `libelle_foyers_imposes`, `notes_source`, `tranches[]`, `colonnes_tranches`, `marques_source`, `communes` (comptes), `totaux_departementaux`, `departements_tranches`), `colonnes`, `definitions`, `ruptures[]`, `regle_null`, `etats`, `statuts_filosofi`, `filosofi[]` (millésime, dispositif, géographie, champ, statuts), `departements[]` (lien `fichier`), `controles` (bilan), `methode`, `limites`, `non_repris`, `sources`, `sources_inaccessibles`, `recherche_publique` |
| `revenus_communes/communes/<dep>.json` | `revenus_communes_communes` | `annees` (années de revenus), `colonnes`, `communes.<insee>` : `nom`, `ircom[]`, `etat`, `perimetre`, `recompose`, `tranches`, `cimr`, `filosofi[]`, `filosofi_anciennes` ; `controles[]` (somme des communes contre total départemental publié) |
| `revenus_communes/tranches/<annee>/<dep>.json` | `revenus_communes_tranches` | `tranches[]` (`libelle` publié, `de_eur`, `a_eur`), `colonnes`, `communes.<insee>` : une ligne par tranche, dans l'ordre de `tranches` ; un fichier par département et par année, s'il a au moins une commune avec ce détail |

| Champ | Sens |
|---|---|
| `communes.<insee>.ircom[k]` | aligné sur `annees` : `[foyers, foyers_imposes, rfr_eur, rfr_imposes_eur, impot_net_eur]` (euros entiers), ou null si la ligne manque ; `impot_net_eur` peut être négatif (restitutions) |
| null dans une ligne | valeur non communiquée par la DGFiP (« n.c. », « n.d. » : secret statistique ; « . » ; « #VALUE! » des revenus 2002 dans le Cher ; cellule vide), pour la commune ou pour l'une des anciennes communes recomposées : jamais 0, jamais estimée (`regle_null`) |
| `etat.<AAAA>` | raison d'une ligne null : `absente` (aucune ligne de la source, par exemple Mayotte avant les revenus 2013, villages sans habitants), `incomplete` (une partie des anciennes communes manque, aucune somme partielle), `perimetre` (un code de la source couvrait aussi le territoire d'une autre commune actuelle, scission postérieure) ; détail dans `perimetre.<AAAA>` |
| `recompose.<AAAA>` | codes de la source dont la ligne est la somme : anciennes communes d'une commune nouvelle, arrondissements de Paris, Marseille et Lyon (codes Insee des arrondissements), ou ancien code d'une commune qui a changé de code |
| `tranches` | années de revenus dont le détail par tranche est dans `tranches/<annee>/<dep>.json` (détail publié par la DGFiP, constaté pour les communes d'environ 1 000 foyers ou plus) |
| `cimr.<AAAA>` | revenus 2018 : `[impot_net_avant_cimr_eur, cimr_eur]` ; `impot_net_eur` de cette année est l'impôt après crédit d'impôt de modernisation du recouvrement (même note « * » de la DGFiP que les autres années) |
| `filosofi[k]` | aligné sur `filosofi_millesimes` (2021, 2023) : `[mediane_eur, menages, statut]` ; `statut` = `publie`, `secret` (statut « C » de l'Insee), `valeur_manquante` (statut « O »), `hors_champ` (Guadeloupe, Guyane, Mayotte ; Martinique aussi en 2023), `absente`, `perimetre` (commune créée après la géographie du millésime : médianes des anciennes communes dans `filosofi_anciennes`, jamais combinées) ; `menages` null en 2023 (non publié à la commune) |
| `controles[]` | par année et grandeur (`foyers`, `rfr_eur`, `impot_net_eur`) : `source` = somme des communes publiées, `autre_source` = total départemental publié, `ecart`, `ecart_pct`, `valeurs_non_communiquees` ; lecture dans `controles_lecture` |
| `ruptures[]` (index) | `annee`, `grandeur`, `type` (`libelle`, `tranches`, `colonnes`, `definition`), `constat`, `lecture`, `citations` : tranches changées (revenus 2003, 2006, 2010), RFR redéfini (revenus 2006, réforme du barème), décompte des foyers (revenus 2011), « foyers imposables » puis « foyers imposés » (revenus 2012), CIMR (revenus 2018) |

**Géographie.** Chaque fichier IRCOM est lu dans sa propre géographie : `geographie_source` = année du code officiel géographique dont la liste de communes diffère le moins de la source (table de passage annuelle de l'Insee). Les fichiers de la DGFiP n'appliquent pas toujours toutes les fusions de l'année : chaque code est lu dans la géographie la plus proche où il existe (quatre ans de part et d'autre, `fenetre_annees`), puis une commune en vigueur reçoit la somme de ses codes source seulement si cet ensemble est exactement son découpage dans une même géographie et qu'aucun de ces codes ne couvre aussi une autre commune en vigueur. Les codes absents de toutes ces géographies (Monaco, Saint-Barthélemy, Saint-Martin, et des codes de la DGFiP absents du code officiel géographique : quatre ou cinq pour les revenus 2002 à 2005, un pour les revenus 2011) sont listés dans `rapprochement.non_rattaches` avec leur nombre de foyers, jamais attribués. Les arrondissements municipaux ne sont pas publiés à part.

**Pour comparer deux communes.** Fichier : `revenus_communes/communes/<dep>.json`, `dep` = département de `local/geo` (deux caractères, `2A`, `2B`, trois pour l'outre-mer). Une même année de revenus se compare d'une commune à l'autre ; une grandeur dérivée (part des foyers imposés = `foyers_imposes / foyers`, RFR moyen ou impôt net moyen par foyer) est un calcul du site, à afficher comme tel avec sa formule, et null dès qu'un terme est null. Dans le temps, lire `ruptures` avant de relier deux années. Une valeur recomposée s'affiche avec la mention de ses anciennes communes (`recompose`). IRCOM (foyers fiscaux, revenu fiscal de référence) et Filosofi (ménages, revenu disponible par unité de consommation) ne s'additionnent pas et ne se comparent pas directement ; Filosofi 2023 (Filosofi 2) n'est pas directement comparable à Filosofi 2021 (Insee). Les tranches ne se comparent qu'à l'intérieur d'un même découpage (même année). Aucune commune n'est classée : l'ordre des clés est celui des codes Insee.

**Règles propres.** Montants convertis en euros entiers (milliers d'euros à trois décimales ou euros selon l'année, `unite_source`). Aucune valeur estimée, aucune somme partielle. Les contrôles comparent la somme des communes publiées au total départemental publié : l'écart vient des valeurs non communiquées, sauf exceptions publiées telles quelles (Ille-et-Vilaine, revenus 2007). Non repris (`non_repris`) : IRCOM 1993 à 2002 (autre format, francs convertis), traitements et salaires, retraites et pensions, foyers non-résidents, Filosofi 2012 à 2020. Taille : le plus gros fichier `communes/<dep>.json` (Pas-de-Calais) fait environ 830 Ko et grossit d'environ 30 Ko par année publiée ; la production s'arrête au-delà de 1 Mo (fichier à découper). Dates par `pipeline/reproductible.py` ; tris explicites : deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.48 Millésimes : exécution 2025 préparée et vérification des éditions attendues : `millesimes/` (pipeline/millesimes.py)

Prépare l'exécution 2025 du budget de l'État dans le format des arbres du site, sans changer la vue par défaut (exécution 2024, `arbre/`), et publie pour chaque source « en retard » de la page de fraîcheur (2.42) ce que les producteurs ont publié à la date du constat. Le passage de la vue par défaut à l'exécution 2025 est soumis au propriétaire du site : `bascule` liste les écrans (web/src) et pipelines qui lisent la vue par défaut, les impacts et les étapes. Commandes : `python collecte/collecte.py etat_plrg_2024 etat_plrg_2025` (réseau, contrôle d'intégrité, refus 401/403/429 jamais contournés), `python pipeline/millesimes.py produire [--sortie DOSSIER]` (sans réseau). Tests : `pytest tests/test_millesimes.py`.

```
data/lake/etat/etat_plrg_2024/, etat_plrg_2025/ (PLRG, annexes 1 et 2, dépenses constatées) ──┐
data/raw/situation_budgetaire.json (prélèvements sur recettes, contrôles au 31/12) ──────────┤
pipeline/grands_postes.json, niveaux.json ; site/data/arbre/racine.json (lecture seule) ─────┼─> pipeline/millesimes.py ─> site/data/millesimes/index.json
web/src/**/*.ts, pipeline/*.py (relevé des lecteurs de la vue par défaut) ───────────────────┘                        site/data/millesimes/execution2025/racine.json
```

| Fichier | Schéma | Contenu |
|---|---|---|
| `millesimes/index.json` | `millesimes_index` | `presentation` ; `vue_par_defaut` (`actuelle` = « Exécution 2024 », `preparee`, `statut`) ; `execution_2025` (`fichier`, `niveaux`, `total_eur`, `perimetre`, `methode`, `publie_le`) ; `controles[]` par année (budget général face aux dépenses nettes de la situation mensuelle, remboursements et dégrèvements retirés, prélèvements sur recettes) ; `comparaison` (`colonnes`, `definitions`, `lignes` par grand poste : exécution 2024 affichée, exécutions 2024 et 2025 selon le PLRG, variation, écart de méthode ; `totaux`, `lecture`) ; `bascule` (`ecrans`, `pipelines`, missions aux libellés différents, `impacts`, `etapes_proposees`) ; `verification` (`date_reference`, `par_suite`, `sources[]` : `id`, `famille`, `axes`, `edition_attendue`, `publication`, `constat`, `url`, `constat_le`, `suite`, `nouvelle_source`, `effet`) ; `sources` ; `recherche_prealable` ; `limites` ; `ordre` |
| `millesimes/execution2025/racine.json` | `arbre_etat` | arbre grand poste > mission > programme de l'exécution 2025 (milliards d'euros, crédits de paiement), même format que `arbre/racine.json` ; pas de niveau action (le PLRG publie par programme et titre) |

**Règles propres.** Les exécutions 2024 et 2025 sont comparées avec la même méthode (dépenses constatées du PLRG, même périmètre que l'arbre du site : budget général hors remboursements et dégrèvements, avances à l'audiovisuel public, prélèvements sur recettes) ; l'exécution 2024 affichée (budget vert retraité au format PLF 2026) n'est montrée qu'avec son écart de méthode, jamais additionnée. Une publication est qualifiée par constat daté (`publié en données ouvertes`, `publié en PDF seulement`, `non publié en données ouvertes`, `non localisé`), sans jugement sur le producteur. Ce module n'écrit ni `arbre/`, ni `meta.json`, ni `web/`. Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

### 2.49 Douane et accises : `douanes_accises/` (pipeline/douanes_accises.py)

Ce que rapportent les accises (énergie, tabacs, alcools) et les droits de douane année après année, ce que la douane perçoit elle-même, et à qui chaque produit est attribué. Trois notions, jamais additionnées entre elles : **produit** (comptabilité nationale, Insee, quel que soit le service qui perçoit), **perçu par la douane** (encaissements de l'année, bilans de la DGDDI), **affecté** (part attribuée à l'État, aux collectivités, à la sécurité sociale ou à l'Union européenne). Ne recopie pas les agrégats de `recettes.json` (Eurostat D214A, D2) ni la ventilation 2025 de `prelevements/affectation.json` : il les désigne (`renvoi_agregats`, `deja_dans_le_site`). Agrégats nationaux seulement. Commandes : `python pipeline/douanes_accises.py collecter` (réseau, par `collecte/collecte.py`, identifiants `douanes_*` du catalogue ; contrôle d'intégrité ; un refus 401/403/429 est noté, jamais contourné), `python pipeline/douanes_accises.py produire [--sortie DOSSIER]` (sans réseau ; `openpyxl`, `xlrd`, `pdfplumber` ; échoue si un montant n'est plus retrouvé à sa ligne dans le document collecté). Tests : `pytest tests/test_douanes_accises.py`.

```
data/lake/douanes_accises/ (Insee tableau 3.217 ; DGDDI classeur 2010-2015 ; bilans de la douane 2020, 2022 à 2025 ;
                            voies et moyens tome I PLF 2024 à 2026 ; PLFSS 2026 annexe 3)
     └─> pipeline/douanes_accises.py ─> site/data/douanes_accises/index.json, produits.json, collecte.json,
                                         affectation.json (chacun < 50 Ko)
```

| Fichier | Schéma | Contenu | Unité | Millésime |
|---|---|---|---|---|
| `douanes_accises/index.json` | `douanes_accises_index` | `presentation` (phrase d'introduction : ce que la page montre et ne montre pas), `notions` (`produit`, `percu_douane`, `affecte`), `fichiers[]`, `renvois[]` (recettes.json, prelevements/affectation.json, ue/contribution.json), `ecarts_entre_sources[]` (par produit : `lignes[]` avec `annee`, `comptes_nationaux_md`, `percu_douane_md`, `ecart_md`, et pour l'accise énergie `voies_et_moyens_brute_totale_md`) et `lecture_ecart`, `ruptures[]` (`annees`, `postes`, `constat`, `lecture`, `documents`), `chiffres_cles`, `sources[]`, `sources_inaccessibles[]`, `recherche_publique` (verdict, trouvailles classées avec licence et date), `confidentialite`, `limites[]`, `verification_documents` | divers | |
| `douanes_accises/produits.json` | `douanes_accises_produits` | `annees` (entiers contigus), `produits[]` (`id`, `libelle`, `libelle_source`, `famille`, `valeurs_md` alignées sur `annees`, `statut` = `trace`) : accise sur les produits énergétiques (ex-TICPE), électricité, gaz naturel, autres taxes sur l'énergie, tabacs, alcools et boissons, droits de douane au profit de l'UE, octroi de mer, TGAP ; `familles` (libellés) ; `renvoi_agregats` | milliards d'euros | 1995 à 2025 (comptes nationaux base 2020) |
| `douanes_accises/collecte.json` | `douanes_accises_collecte` | `annees` (années publiées : 2010 à 2015, 2019 à 2025), `editions[]` (document source de chaque année), `postes[]` (`id`, `libelle`, `groupe`, `valeurs_m` alignées sur `annees`, `null_raisons` par année), `calculs[]` (deux totaux de groupe recomposés pour 2010-2015, formule écrite), `coherence[]` (total publié, somme des groupes, écart), `destination[]` (2024 et 2025 : parts en % de l'État, des collectivités et organismes sociaux regroupés par la source, de l'UE ; `statut`, `lecture`), `destinataires`, `groupes` | millions d'euros | 2010 à 2025 |
| `douanes_accises/affectation.json` | `douanes_accises_affectation` | `destinataires` (nom, administration) ; `energie` : `editions[]` des voies et moyens (trois colonnes chacune, `statuts` = `execution`, `prevision`, `prevision_revisee` ; `lignes[]` avec `destinataire`), `executions` (colonne « Exécution » de chaque édition : 2022, 2023, 2024), `lecture_signes`, `deja_dans_le_site` ; `tabacs` et `alcools` : `cles` (`annees` 2018 à 2026, `parts[]` par destinataire en %) ; `montants_plfss` (prévisions 2025 et 2026 par droit, M€) ; `droits_de_douane` : `regle` (citations), `frais_perception[]` (part conservée par l'État, ligne 2301, 2021 à 2026, avec `citation`) | Md€, M€, % | 2018 à 2026 |

| Champ | Sens |
|---|---|
| `statut` | `trace` (valeur lue telle quelle), `approche` (lecture qui suppose une attribution : destination 2025, voir `lecture`), `non_publie` ; à afficher avec les motifs du site (plein, pointillé, hachuré) |
| `null` | case « * » (transfert de taxe), « - », ligne absente de l'édition ou « N.D. » : jamais 0 ; la raison est dans `null_raisons` (collecte) ou dans `lecture` (clés) |
| `postes[].groupe` | `dedouanement`, `energie_environnement`, `contributions_indirectes`, `octroi_mer_maritime`, `tsvr`, `autres`, `total` ; les postes « (total du groupe) » sont les totaux publiés, ne pas les ajouter à leurs lignes |
| `ecart_md` | `comptes_nationaux_md` moins `percu_douane_md`, même produit, même année : notions différentes, aucune n'est retenue à la place de l'autre |
| `deja_dans_le_site` | fichier et clé où la même année est déjà publiée (2025) : l'écran lit ce fichier-là pour 2025 |

**Pour l'écran.** Phrase d'introduction : `index.presentation`. Série longue par produit : `produits.json` (une courbe par `famille`, années de `annees`, source Insee). Ce que perçoit la douane : `collecte.json`, avec les `ruptures` de `index.json` affichées sur les années concernées (2021-2022 : TVA à l'importation ; 2021-2023 : taxes transférées ; 2024-2025 : tabacs et alcools, perception transférée à la DGFiP) : une baisse dans `collecte.json` n'est pas une baisse du produit de la taxe, à lire avec `produits.json`. Les années 2016 à 2018 n'existent pas dans `collecte.json` (aucune interpolation : laisser un trou). À qui va chaque euro : `affectation.json` (barres empilées par destinataire, signe des transferts dans `lecture_signes`), `collecte.destination` pour la vue d'ensemble 2024 et 2025 (2025 en pointillé, `statut` = `approche`). Écarts : tableau `index.ecarts_entre_sources` (trois colonnes côte à côte, aucune « bonne » valeur). Chaque montant avec son année, son unité (Md€ ou M€ selon le fichier) et sa source (`sources[].url`).

**Règles propres.** Montants lus dans un PDF écrits dans le module (tables `LECTURES_*`) puis retrouvés à leur ligne dans le document collecté à chaque production (`verification_documents`) ; un motif manquant arrête la production. Aucune estimation, aucune somme entre notions ; deux sommes seulement, écrites dans `calculs` (groupes du classeur 2010-2015 recomposés au découpage des bilans). La cohérence total publié / somme des groupes est publiée telle quelle (écarts de la source en 2023 et 2025). Sources inaccessibles (`index.json`) : aucune refusée ; recettes de la douane par produit après 2015 non publiées en données ouvertes (constat du 18/11/2026). Dates par `pipeline/reproductible.py` ; deux productions sur le même entrepôt sont identiques octet pour octet.

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
