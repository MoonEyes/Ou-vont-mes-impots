# Schémas à reporter dans le contrat d'interface : axe « Près de chez moi » (`site/data/local/`)

Proposition pour la version **1.2** du contrat (ajout de fichiers, rien de renommé). Producteur : `pipeline/local.py`. Montants en **euros** (pas en Md€). Tous les fichiers portent `millesime` et `source`. `null` = absent à la source, jamais 0.

```
geo.api.gouv.fr ─┐                          ┌─> geo/<dep>.json
OFGL (API filtrée par département, cache) ──┤─> budgets/communes/<dep>.json, dotations/communes/<dep>.json
data/lake (OFGL GFP, EI, départements,      ├─> budgets/epci/<dep>.json, budgets/departements.json, budgets/regions.json
  régions, REI, DGCL, SCDL, Mégalis, ...)  ─┤─> budgets/fonctions/*.json, dotations/*.json, taux/<dep>.json
stock SIRENE (catégorie juridique) ─────────┘─> decisions/<siren>/*.json, decisions/index.json, index.json
```

Commandes :

```bash
python pipeline/local.py tout --deps 44,22,29,35,56          # mode département (pilote)
until python pipeline/local.py tout --tous; do sleep 1; done  # France entière, une ligne, reprenable
pytest tests/test_local.py                                    # sans réseau
```

Chaque passage est borné (`--budget`, 480 s par défaut) ; l'export OFGL filtré prend 30 à 120 s par département (6 en parallèle). Les extraits sont mis en cache dans `data/lake/_cache/local/` (non versionné) ; code de sortie 3 tant qu'il reste des départements. Les niveaux nationaux (EPCI, départements, régions, taux, dotations EPCI/départements/régions, décisions) sont régénérés à chaque passage depuis l'entrepôt.

## Rattachement et lecture côté site

1. `index.json` : `communes.<insee>` est un masque de bits ; le bloc `blocs[i]` est disponible si `(valeur >> i) & 1`. `sirens.departements` et `sirens.regions` donnent le SIREN à utiliser pour `decisions/<siren>/` et `budgets/fonctions/<siren>.json`.
2. `geo/<dep>.json` (département = 2 premiers caractères du code INSEE, 3 en outre-mer) : `communes.<insee> = {nom, population, siren, epci, departement, region}`, `epci.<siren> = {nom, population, departement_siege}`.
3. Les comptes de l'EPCI sont dans `budgets/epci/<departement_siege>.json` (siège selon l'OFGL ; un EPCI peut déborder du département).

## Budgets (`budgets/communes/<dep>.json`, `budgets/epci/<dep>.json`, `budgets/departements.json`, `budgets/regions.json`)

| Champ | Type | Sens |
|---|---|---|
| `annees` | `["2022", ...]` | les 4 derniers exercices clos publiés par l'OFGL |
| `agregats` | tableau de clés | ordre des valeurs ; libellé OFGL exact dans `libelles_ofgl` |
| `collectivites.<code>` | objet | code INSEE (communes), SIREN (EPCI), code département ou région |
| `.nom`, `.siren` | chaînes | |
| `.population.<annee>` | entier | population totale OFGL de l'exercice |
| `.eur.<annee>` | tableau aligné sur `agregats` | euros, arrondis à l'euro |
| `.eur_hab.<annee>` | tableau aligné | `eur / population`, 2 décimales (vérifié par les tests) |

Agrégats : `depenses_fonctionnement`, `frais_personnel`, `achats_charges_externes`, `depenses_intervention`, `subventions_versees_fonctionnement` (subventions aux personnes de droit privé), `charges_financieres` (intérêts), `depenses_investissement` (hors remboursements), `depenses_equipement`, `subventions_versees_equipement`, `remboursement_dette`, `depenses_totales`, `recettes_fonctionnement`, `impots_taxes`, `impots_locaux`, `fiscalite_reversee`, `concours_etat`, `dgf`, `subventions_recues`, `ventes_biens_services`, `epargne_brute`, `encours_dette`. Comptes consolidés OFGL : budget principal + budgets annexes, flux internes neutralisés.

`budgets/epci/<dep>.json` ajoute `bloc_communal_consolide.<siren>` (même format) et `methode_bloc_communal`.

### Méthode anti double compte (publiée dans chaque fichier EPCI)

On n'additionne jamais commune + EPCI. Le bloc communal est l'« ensemble intercommunal » OFGL (`ofgl-base-ei`) : GFP + communes membres, `montant = montant_gfp + montant_communes - montant_flux`, ce qui retire les attributions de compensation et la dotation de solidarité communautaire (la `fiscalite_reversee` du bloc devient proche de 0 ; il reste le FPIC et le FNGIR, qui sont des flux avec l'extérieur), les subventions et participations croisées, les remboursements de frais. Euros par habitant du bloc : population du territoire intercommunal. Département et région ne sont jamais additionnés au bloc (leurs subventions aux communes seraient comptées deux fois). Test : bloc ≤ EPCI + communes membres.

## Détail par fonction

- `budgets/fonctions/departements.json` (tous les départements, OFGL fonctionnelle, niveau 1) : `departements.<code> = {nom, population.<annee>, fonctions.<code fonction> = {libelle, eur.<annee> = [fonctionnement, investissement hors remboursements], eur_hab.<annee>}}`.
- `budgets/fonctions/<siren>.json` (pilote) : collectivités bretonnes qui votent par fonction (budgets Mégalis, comptes administratifs, M57, exercices ≥ 2024), Nantes Métropole (comptes administratifs) et Ville de Nantes (budgets primitifs : crédits votés, signalé dans `millesime`). Dépenses réelles hors chapitre 16 (emprunts). `population` : geo.api.gouv.fr.

## Dotations (`dotations/communes/<dep>.json`, `dotations/epci.json`, `dotations/departements.json`, `dotations/regions.json`)

`communes.<insee>.eur.<annee>.<cle>` (montants notifiés, euros) : `dgf_totale`, `dgf_forfaitaire`, `dgf_dsu`, `dgf_dsr`, `dgf_dnp`, `dgf_commune_nouvelle`, `dgf_dacom`, `dotation_biodiversite`, `dcrtp`, `dilico_prelevement` (montant retenu, positif, à déduire), `dilico_reversement`. EPCI : `dgf_totale`, `dgf_intercommunalite`, `dgf_compensation`, `dctp`. Départements : `dgf_totale`, `dgf_forfaitaire`, `dgf_compensation`, `dgf_perequation_urbaine`, `dgf_fonctionnement_minimale`, `dcrtp`. Régions : fonds de péréquation (la DGF régionale est remplacée par une fraction de TVA depuis 2018).

`investissement_etat.<insee ou siren>.<annee> = {total, par_dispositif, nb_projets, projets: [[dispositif, intitulé, subvention, coût HT]]}` (DETR, DSIL, DPV, DSID ; 15 plus gros projets).

## Taux (`taux/<dep>.json`)

`communes.<insee>.<exercice>` = tableau aligné sur `colonnes` (%) : `tfb_commune`, `tfb_syndicats`, `tfb_intercommunalite`, `tfb_taxe_speciale_equipement`, `tfb_gemapi`, `tfb_global`, `tfnb_commune`, `tfnb_intercommunalite`, `tfnb_global`, `thrs_commune`, `thrs_intercommunalite`, `thrs_global`, `teom_taux_plein`. Trois derniers exercices du REI. Complète `communes/<dep>.json` (contrat 1.0, inchangé).

## Décisions (`decisions/`)

### Règle personnes physiques (bloquante)

Un bénéficiaire n'est nommé que si son SIREN (9 premiers chiffres du SIRET publié) a une catégorie juridique `2xxx` à `9xxx` dans le stock SIRENE. Le reste est agrégé dans `exclus_personnes_physiques_ou_non_identifies` (`montant_eur`, `lignes`, `dont_personnes_physiques_eur`, `dont_sans_siren_eur`, `dont_categorie_inconnue_eur`). Les objets contenant une civilité (M., Mme, Monsieur...) sont remplacés par `null`. Aucun champ « prénom ».

### `decisions/<siren>/<annee>.json` (ou `<annee>-<n>.json` au-delà de 10 000 lignes)

`{collectivite: {type, code, siren, nom}, annee, colonnes, lignes}`, colonnes : `date_decision`, `reference_decision`, `siren`, `categorie_juridique`, `denomination` (SIRENE), `montant_eur`, `objet` ; Région Pays de la Loire : + `mandate_eur`, `programme`. Lignes triées par montant décroissant. Année : date de décision ou de convention, à défaut année du jeu ; Région PdL : année de l'opération (préfixe du numéro d'opération).

### `decisions/<siren>/index.json`

`total_source_eur`, `lignes_source`, `annees.<a> = {lignes, montant_eur, fichiers[], mandate_eur?}`, `top_beneficiaires[≤50] = {siren, denomination, categorie_juridique, montant_eur, lignes}`, `personnes_morales`, `exclus_...`, `deliberations_par_annee.<a>` (nombre d'actes publiés), `deliberations_subventions.<a> = [[date, id, objet, url]]` (matière 7.5, 3 dernières années). Conservation : `somme(annees.montant_eur) + exclus.montant_eur = total_source_eur` (à l'euro près par année). Région PdL : `total_mandate_eur`, `programmes.<code> = {libelle, nb_deliberations, deliberations: [{date, url}]}` (lien code programme → délibérations, l'objet des délibérations commençant par le code programme).

### `decisions/index.json`

`couverture.<commune|epci|departement|region> = {couvertes_subventions, couvertes_deliberations, total, part_pct}`, `collectivites.<siren> = {type, code, nom, lignes, annees, total_eur}`, `attribuants_hors_collectivites`, `limites`.

## Limites connues

- Comptes OFGL : derniers exercices clos ; communes nouvelles ou fusionnées absentes certaines années ; Paris, Martinique, Guyane, Mayotte et la Corse suivent le découpage OFGL (collectivités à statut particulier).
- Détail par fonction : la plupart des communes de moins de 3 500 habitants ne votent pas par fonction ; pas de présentation fonctionnelle publiée pour les régions.
- Subventions SCDL : publication très partielle (obligatoire au-dessus de 23 000 € seulement) ; une collectivité absente n'a pas forcément versé moins. Les dates manquent parfois (année `inconnue`).
