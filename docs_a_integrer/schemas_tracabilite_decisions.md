# Schémas à reporter dans le contrat d'interface (traçabilité, décisions)

Proposition pour la version **1.1** du contrat (ajout de fichiers, rien de renommé). Producteurs : `pipeline/tracabilite.py` et `pipeline/decisions.py`. Montants en **euros**. Chaque fichier porte `millesime` et `source`.

```
arbre/ + nature/ + beneficiaires/ + vie_politique/ + PLRG 2023  ─> pipeline/tracabilite.py ─> tracabilite/
AN L17 (amendements, scrutins, dossiers, acteurs) + Sénat Ameli (COPY) + JORF DILA + PLRG 2023-2025
                                                               ─> pipeline/decisions.py  ─> decisions/
```

Commandes : `python pipeline/tracabilite.py` (sans réseau, < 1 s) ; `python pipeline/decisions.py jorf` (archive JORF lue en flux, environ 4 min, cache `data/lake/_cache/decisions_jorf/`, reprenable) puis `python pipeline/decisions.py produire` (sans réseau, environ 40 s). Tests : `pytest tests/test_tracabilite.py tests/test_decisions.py`.

## `tracabilite/programme_<n>.json` et `tracabilite/noeud_psr_<x>.json`

Un fichier par programme de l'arbre exécution 2024, plus les deux prélèvements sur recettes (feuilles de niveau mission).

| Champ | Type | Sens |
|---|---|---|
| `annee`, `millesime`, `source`, `unite` | chaînes | `"2024"`, `"Exécution 2024"` |
| `niveau`, `programme`, `id_arbre`, `libelle`, `mission`, `grand_poste` | | rattachement à `arbre/` |
| `total_eur` | nombre | montant du noeud dans l'arbre |
| `parts.<part>` | `{libelle, eur, pct, statut, ecart_millesime_ans, sources[]}` | partition du noeud ; les `pct` somment à 100 |
| `maillons[]` | `{maillon, libelle, pct, statut, sources[]}` | couvertures : `programme` (100), `nature`, `destinataire`, `beneficiaire_nomme` |
| `taux_tracabilite_pct` | nombre | part des euros dont le destinataire est connu (trois premières parts) |
| `composantes.<part>[]` | `{eur, sources[], millesime, statut, ecart_millesime_ans, raison_approche, detail, niveau_identification}` | détail par source ; `niveau_identification` : `entite`, `categorie`, `aucun` |
| `ecrete_eur`, `note_ecrete` | | montant des sources dépassant la place disponible (non compté) |

Parts : `beneficiaire_identifie` (associations nommées, marchés de l'État, France 2030, partis et remboursements de campagne, bénéficiaire unique désigné par le programme, prélèvements sur recettes, dotations aux collectivités), `nominatif_par_choix` (titre 2), `anonyme_par_nature` (catégories 41 à 43, programme 369), `non_publie`.

Statut : `exact` si numérateur et dénominateur sont de la même année et de même nature ; sinon `approche`, avec `ecart_millesime_ans` (associations : 1 an, taux 2023 calculé sur les dépenses 2023 du PLRG 2023 puis appliqué à 2024) et `raison_approche` (marchés notifiés et non payés, rattachés au ministère ; France 2030 : engagements cumulés). Un programme net négatif (423) est rangé à 100 % en `non_publie`.

## `tracabilite/resume.json`

`global`, `grands_postes[]`, `missions[]` (même structure que ci-dessus sans `composantes`), `programmes[]` (`{id, libelle, mission, grand_poste, fichier, total_eur, taux_tracabilite_pct, <part>_pct, approche}`), `methode`, `limites[]`.

## `decisions/programme_<n>.json`

| Champ | Type | Sens |
|---|---|---|
| `programme`, `libelle`, `mission`, `dans_arbre_2024` | | |
| `annees.<AAAA>` | objet | `lfi_cp`, `lfr_cp`, `reports_entrants_cp`, `mouvements_reglementaires_plrg_cp`, `fonds_de_concours_plrg_cp`, `ouverts_cp`, `depenses_cp`, `source_plrg` (2023 à 2025) ; `controle_jo_plrg.<colonne>` ; `amendements` (comptes) ; `amendements_adoptes[]` ; `mouvements_jo[]`, `mouvements_jo_total_cp` |
| `annees.*.amendements_adoptes[]` | | `{id, chambre, texte, annee, lecture, lieu, numero, sort, date, auteur{type, nom, groupe, masque?}, cosignataires, ae, cp, net_cp_amendement, rapprochement, scrutins[], url}` ; `ae`/`cp` = ligne du programme, signées |
| `annees.*.mouvements_jo[]` | | `{id, date, annee, type, titre, ae, cp, url}` (Légifrance) |
| `chronologie[]` | | `{date, annee, etape, cp, ae?, auteur?, url?, source?}` triée : LFI votée, amendements adoptés, décrets et arrêtés, LFR, exécution |

## Autres fichiers de `decisions/`

- `amendements_resume.json` : `par_programme.<n>.<AAAA>` = `{deposes_an, deposes_senat, adoptes_seance_an, adoptes_seance_senat, adoptes_commission_an, net_ae_adopte_seance, net_cp_adopte_seance, net_cp_adopte_commission_an}` ; `lignes_non_rattachees`.
- `scrutins.json` : `scrutins[]` = `{id, numero, date, texte, annee, type, objet, resultat, pour, contre, abstentions, votants, amendement, url}` ; `type` parmi `ensemble`, `premiere_partie`, `seconde_partie`, `credits_mission`, `article_equilibre`, `article`, `motion`, `amendement`, `autre`.
- `mouvements_<AAAA>.json` (2021 à 2026) : `textes[]` = `{id, titre, type, libelle_type, categorie_plrg, date, date_publication, nor, annee_gestion, rectificatif, url, lignes_perdues, lignes[{programme, ae, cp}], total_cp}`. Signe : ouverture > 0, annulation < 0.
- `coherence_plrg.json` : `tolerance` (`pct_par_annee` = 1 %, `eur_par_programme` = 1 000 €), `composition`, `annees.<AAAA>.<colonne>` = `{total_jo_cp, total_plrg_cp, somme_valeurs_absolues_plrg_cp, ecart_absolu_cp, ecart_pct, conforme, programmes_conformes, programmes, ecarts[]}`.
- `index.json` : `programmes`, `fichiers`, `comptes`, `coherence_plrg`, `regle_personnes`, `limites`.

## Règle personnes

Auteurs : `{type, nom, groupe}` ; seuls les élus, le Gouvernement et les commissions sont nommés. Un élu qui a été candidat national (présidentielle, tête de liste européenne) est publié sans nom (`masque`), conformément à `tests/test_vie_politique.py`. Aucune date de naissance, adresse ni profession n'est lue.
