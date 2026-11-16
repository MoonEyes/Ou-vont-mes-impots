# Schéma à reporter dans le contrat d'interface : bloc « Ce qui a été fait » (réalisations)

Proposition pour la version **1.2** du contrat (ajout de fichiers, rien de renommé). Producteur : `pipeline/realisations.py`. Montants en **euros** (crédits de paiement) ; `eur_sur_100` = dépense 2024 / total de l'arbre État (`arbre/racine.json`) × 100, à lire « X € sur 100 € du budget de l'État ». Chaque fichier porte `millesime`, `source` et `avertissement` (texte fixe : « Les indicateurs sont choisis par l'administration ; une évolution ne prouve pas l'effet de la dépense. »).

```
data/lake (PLRG 2023-2025 annexe 1 « état CP », RAP de synthèse 2019-2020, budget vert PLF 2024,
           exécution 2010-2014 et LFI 2011-2014, RAP/PAP 2015-2025 volet performance)
   + ccomptes.fr (pages « Le budget de l'État en <année> », flux RSS publications, vérification HTTP des liens)
   + site/data/beneficiaires/ (programme_<n>.json, france2030.json)
        └─> pipeline/realisations.py ─> site/data/realisations/<programme>.json  site/data/realisations/index.json
```

Commandes : `python pipeline/realisations.py collecter` (réseau, reprenable, `--budget` secondes pour la vérification des liens ; écrit dans `data/lake/etat/realisations/` et `data/lake/_cache/ccomptes/`), puis `python pipeline/realisations.py produire` (sans réseau). Tests : `pytest tests/test_realisations.py`.

## `realisations/<programme>.json`

Un fichier par programme présent dans les annexes PLRG 2023 à 2025 (135).

| Champ | Type | Sens |
|---|---|---|
| `millesime`, `source`, `avertissement` | chaînes | |
| `programme`, `libelle`, `mission` | chaînes | `programme` sur 3 chiffres, libellés du dernier PLRG |
| `prevu_depense` | objet | bloc 1 |
| `resultats_mesures` | objet | bloc 2 |
| `realisations_concretes` | objet | bloc 3 |
| `evaluations` | objet | bloc 4 |

### 1. `prevu_depense`

`annees[]` (ordre chronologique), `lecture`, `note_perimetre` ; `note` si le programme n'a aucune année.

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

Sources par année : 2010-2014 exécution du budget général (`execution-2010...`, `...2011...`, `...2012...`, `...2013...`, `plr-2014...`) et LFI 2011-2014 (`lfi-2012...`, `lfi-2013...`, `lfi-2014...`) ; 2018 consommation lue dans le RAP de synthèse 2019 ; 2019 et 2020 RAP de synthèse (`projet-de-loi-de-reglement-2019-plr-20192`, `projet-de-loi-de-reglement-2020-plr-2020`, feuille « Crédits ») ; 2022 budget vert PLF 2024 (`execution_2022_cp`, crédits budgétaires) ; 2023-2025 PLRG, annexe 1 « état CP ».

### 2. `resultats_mesures`

`indicateurs[]` (une entrée par couple indicateur × sous-indicateur, les plus récents d'abord), `note` (si aucun indicateur), `lecture`.

| Champ | Type | Sens |
|---|---|---|
| `id` | chaîne | `<programme>-<n>`, stable à données égales |
| `code_indicateur` | chaîne ou `null` | code externe `P141-1-2` (normalisé depuis `P141.1.2` et `141-1-2`) |
| `objectif`, `indicateur`, `sous_indicateur`, `unite` | chaînes | libellés de la source la plus récente |
| `libelles_anterieurs` | tableau ou `null` | autres libellés rapprochés de la même série |
| `indicateur_de_contexte` | booléen ou `null` | colonne `contexte` du RAP 2025 |
| `valeurs[]` | `{annee, valeur, brut, source}` | réalisé ; `valeur` nettoyée (virgule décimale, espaces, « (± x) ») ou `null` (« nd », « sans objet »...) ; `brut` = texte publié |
| `cibles[]` | `{annee, valeur, brut, source, note?}` | cible du PAP de l'année ; `note: "cible de moyen terme"` pour `valeur_cible` / `annee_cible` |
| `ecarts_a_la_cible[]` | `{annee, realise, cible, ecart, atteinte_publiee}` | `ecart = realise - cible` ; `atteinte_publiee` = texte de la source (« cible atteinte », « amélioration »...) |
| `sens_souhaite` | `{valeur, methode, source, justification, comparaisons?}` | `valeur` : `hausse`, `baisse`, `stabilité` ou `inconnu` ; `methode` : `colonne evolution` (RAP 2025), `position des cibles` (toutes les cibles au-dessus, ou toutes en dessous, du dernier réalisé connu avant elles), ou `null` |
| `tendance` | objet | `valeur` : `en progrès`, `en recul`, `stable` (variation ≤ 1 % entre les deux dernières valeurs), `sens inconnu` ; `de_annee`, `a_annee`, `de`, `a`, `variation`, `variation_relative_pct` ; `justification` (progrès ou recul) ou `raison` |
| `rapprochement` | objet | nombre de lignes source rattachées par `code`, `libellé`, `création` |

Rapprochement des séries : sources lues de la plus récente à la plus ancienne (RAP 2025, exécution et atteinte 2022-2024, RAP 2024, PAP 2025, PAP 2023, RAP 2020, RAP 2019, PAP 2019, PAP 2018, RAP 2016, PAP 2017, RAP 2015, PAP 2016, PAP 2015) ; une valeur d'une année vient de la source la plus récente qui la publie. Une ligne rejoint une série par code externe si le libellé d'indicateur partage au moins la moitié de ses mots (garde contre les renumérotations), puis par libellé exact (indicateur et sous-indicateur). `facteur_de_performance` (Citoyen, Usager, Contribuable) ne donne pas de sens et n'est pas utilisé.

### 3. `realisations_concretes`

| Champ | Type | Sens |
|---|---|---|
| `liste[]` (≤ 10, montant décroissant) | `{objet, beneficiaire, siren, montant_eur, eur_sur_100, type}` | repris de `beneficiaires/programme_<n>.json` (associations, crédits 2023) |
| `fichier_beneficiaires` | chaîne ou `null` | renvoi, chemin relatif à `site/data/` |
| `france2030` | objet ou `null` | programmes 424 et 425 : `{total_eur, projets, millesime, source, fichier, note}` |
| `millesime`, `source`, `note` | chaînes | |

### 4. `evaluations`

| Champ | Type | Sens |
|---|---|---|
| `liens[]` | objet | `type` (« note d'exécution budgétaire (NEB) » ou « publication »), `annee_execution`, `titre`, `titre_publie`, `url` (PDF), `page`, `rattachement`, `verifie: true`, `verifie_le`, `statut_http: 200` |
| `liens_ecartes_non_verifies` | entier | liens rattachés mais non vérifiés (jamais publiés) |
| `note` | chaîne ou `null` | raison d'un champ vide (ex. mission « Pouvoirs publics », sans NEB) |

Rattachement fiable seulement : titre de la NEB, sans l'année finale, égal au nom exact de la mission ; pour 2015 et 2016 (pages sans titre) le titre vient de la NEB d'une autre année au même nom de fichier ; pour 2020 à 2022 la page `/fr/documents/<n>` est lue et son unique PDF `NEB-<année>-...` retenu. Flux RSS : titre contenant le nom exact du programme, ou de la mission si elle a au moins trois mots. Un lien n'est publié qu'après un appel HTTP 200 (et contenu PDF pour les NEB).

## `realisations/index.json`

`millesime`, `source`, `avertissement`, `programmes[]`, `fichiers`, `couverture` (programmes ayant chaque bloc), `trous_execution`, `annees_execution`, `annees_performance`, `sources_performance`, `rapprochement_indicateurs`, `tendances` (comptes par valeur), `fiabilite_regle_position_cibles` (concordance de la règle de repli avec la colonne `evolution` là où les deux existent, 78 %), `reculs_les_plus_marques` et `reculs_criteres`, `evaluations` (NEB trouvées, années, liens vérifiés).
