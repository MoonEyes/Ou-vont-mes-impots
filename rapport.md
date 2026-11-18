# Rapport renfort-site (vague 3)

| Mission | Branche | Hash | Résumé | GitHub Actions |
|---|---|---|---|---|
| q01_page-numerique-etat | agent/page-numerique-etat | bf83db4 | Page /explorer/numerique-etat : panorama DINUM (22 éditions, 165 projets), coûts par projet et par ministère, 5 fonds sans total. | succès (44268019693) |
| q02_page-outre-mer | agent/page-outre-mer | 0aa5349 | Page /explorer/outre-mer : crédits par collectivité d'outre-mer (6 territoires), détail par mission, recoupement OFGL, dépenses fiscales. | succès (44266871365) |
| q03_page-formation | agent/page-formation | ec5feef | Page /explorer/formation-professionnelle : programme 103, France compétences, compte personnel de formation et financeurs. | succès (44267329852) |
| q04_page-subventions | agent/page-subventions | 5718896 | Page /beneficiaires/subventions : conventions de subvention et liste des associations côte à côte, recherche par nom ou SIREN. | succès (44268068783) |
| q05_page-marches | agent/page-marches | a9c00ce | Page /beneficiaires/marches et 4 nouveaux fichiers du pipeline marches (DECP 2019 à 2025, règle de dédoublonnage 2021, repère OECP). | échec (44269752538) : test_datapackage seul, lancer `python pipeline/datapackage.py` à l'intégration |
| q06_page-territoires | agent/page-territoires | 587051c | Blocs territoires ajoutés aux pages commune et département prérendues (projets aidés, SRU, syndicats, eau, aide sociale), pas de route à part. | succès (44267813883) |
| q07_page-recouvrement | agent/page-recouvrement | 16e281f | Page /explorer/recouvrement : contrôle fiscal, redressements Urssaf, frais de gestion, 7 estimations de fraude côte à côte. | succès (44275322505) |
| q08_page-comparaison-europe | agent/page-comparaison-europe | 8e545ba | Page /explorer/comparaison-europe : 27 pays par fonction COFOG et prélèvements, sans rang, France en repère. | succès (44275269830) |
| q09_recap-partage | agent/recap-partage | 927e1ae | Image PNG de partage sans montant personnel par défaut, bouton Imprimer et feuille d'impression. | succès (44272889561) |
| q10_comparer-communes | agent/comparer-communes | 40933a4 | Écran /local/comparer : deux communes côte à côte par habitant, adresse partageable, revenu médian en attente de l'axe revenus_communes. | succès (44271538176) |
| q11_series-longues | agent/series-longues | a250f92 | Page /explorer/series et axe pipeline/series.py : séries 2005 à 2025 en euros courants, constants ou part du PIB. | échec (44273428217) : test_datapackage seul, lancer `python pipeline/datapackage.py` à l'intégration |
| q12_suivre-un-euro | agent/suivre-un-euro | 37019a4 | Page /suivre-un-euro : un euro suivi étape par étape depuis 19 prélèvements, avec l'endroit où la piste s'arrête. | succès (44271843616) |
| q13_export-csv-citer | agent/export-csv-citer | f747c77 | Boutons « Télécharger (CSV) » et « Citer » sous chaque tableau, sans dépendance. | succès (44271626955) |
| q14_signaler-erreur | agent/signaler-erreur | 8cdca4f | Lien « Signaler une erreur » sur chaque page vers un ticket GitHub pré-rempli, avec gabarit de ticket. | échec (44271473992) : tests/bundle.test.ts ligne 59 refuse tout lien https dans dist/index.html ; correction proposée : retirer les balises `<a>` avant le contrôle, comme prerendu.test.ts |
| q15_pwa-hors-ligne | agent/pwa-hors-ligne | 03c2950 | Manifeste et service worker : pages déjà vues lisibles hors ligne avec date de copie et millésime affichés. | succès (44275326001) |
| q16_performance-prerendu | agent/performance-prerendu | 8576a4d | Carte en trame mise en un seul SVG partagé : HTML prérendu de 99,3 à 62,2 Mo, budgets de poids testés. | succès (44275795790) |

## Points à arbitrer remontés par les agents

- Pages sans lien entrant (fichiers hors périmètre) : numerique-etat, recouvrement, comparaison-europe (hub Explorer à tuiles fixes), /local/comparer.
- Ligne Claude-Session des commits : selon les agents, celle de REGLES.md ou celle de la session ; les deux variantes coexistent.
- subventions : une dénomination d'association du programme 163 contient un nom de personne dans les données publiées.
- marches : seuil de la règle 2021 (3 marchés, 100 M€) qui peut écarter des séries UGAP réelles ; un marché isolé de 12,3 Md€ (2024) reste dans les totaux ; tous les fichiers marches ont été régénérés.
- performance-prerendu : les 100 liens vers les autres départements sont remplacés par un lien vers /local sur les pages commune et département.
- comparer-communes : forme attendue de revenus_communes/<dep>.json à aligner avec l'axe correspondant.
- Branche de test agent/test-acces-renfort-site : poussée à l'étape 1 mais sa suppression a été refusée par le proxy de cette machine ; elle reste sur origin et peut être supprimée.
