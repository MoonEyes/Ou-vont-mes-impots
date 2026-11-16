# Rapport de collecte de l'entrepot brut

Genere le 2026-11-16T12:36:00+00:00 par `collecte/rapport.py` a partir de `data/lake/manifest.json`.

## Vue d'ensemble

- Sources suivies : 6152 (ok : 5676, en erreur ou delai depasse : 329, sans fichier ou lourdes differees : 147)
- Fichiers : 11006, volume : 20,337.6 Mo
- Lignes comptees (Parquet et CSV) : 63 471 022
- Origine : 111 du catalogue manuel, 6041 des decouvertes automatiques
- Espace disque libre : 10.0 Go

## Par domaine

| Domaine | Sources | OK | Erreurs | Fichiers | Mo | Lignes |
|---|---:|---:|---:|---:|---:|---:|
| aides_entreprises | 15 | 15 | 0 | 27 | 15.7 | 167 692 |
| beneficiaires | 1365 | 1242 | 67 | 2586 | 1 904.7 | 9 921 329 |
| collectivites | 2124 | 1999 | 105 | 3004 | 7 216.0 | 35 022 769 |
| comptes_nationaux | 9 | 9 | 0 | 9 | 21.7 | 0 |
| decisions | 56 | 55 | 1 | 498 | 3 603.8 | 888 776 |
| dette | 151 | 151 | 0 | 278 | 70.2 | 345 384 |
| divers | 362 | 324 | 26 | 771 | 757.7 | 1 647 423 |
| etat | 1390 | 1257 | 90 | 2277 | 1 351.2 | 4 970 552 |
| europe | 106 | 103 | 2 | 426 | 740.8 | 1 651 038 |
| fiscalite | 250 | 224 | 15 | 421 | 3 925.4 | 4 688 282 |
| politique | 56 | 52 | 1 | 125 | 404.2 | 519 764 |
| secu | 268 | 245 | 22 | 584 | 325.9 | 3 648 013 |

## Erreurs (329)

Par cause : budget de temps depasse 133, hote injoignable 90, lien mort (404) 38, acces refuse (non contourne) 29, autre 21, parquet tronque 18.

- `caf__aah_s_sexe_age_5_dep` [erreur] : https://data.caf.fr/api/explore/v2.1/catalog/datasets/aah_s_sexe_age_5_dep injoignable apres 6 tentatives : ConnectionError: ('Connection aborted.', ConnectionR
- `datagouv__1-2-million-de-travailleurs-sociaux-en-2011` [erreur] : toutes les ressources en echec, ex. http://www.drees.sante.gouv.fr/IMG/pdf/er893.pdf injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.dr
- `datagouv__1695047341709-1-1` [delai_depasse] : budget de temps epuise avant https://grandestprod.data4citizen.com/data4citizen/sites/default/files/dataset/2023/09/29/c63f0025-ea5a-4d83-afef-e378daa19ed9/budg
- `datagouv__1695387641865-1` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695387641865-11695387641865-1/conseil-departemental-meuse-2018-PRINC
- `datagouv__1695388365181-1` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388365181-11695388365181-1/conseil-departemental-meuse-2020-PRINC
- `datagouv__1695388552745-2` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388552745-21695388552745-2/conseil-departemental-meuse-2021-PRINC
- `datagouv__1695388704140-3` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388704140-31695388704140-3/conseil-departemental-meuse-2022-PRINC
- `datagouv__3-8-millions-de-prestations-daide-sociale-attribuees-par-les-departements-en-2013` [erreur] : toutes les ressources en echec, ex. http://www.drees.sante.gouv.fr/IMG/pdf/er900.pdf injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.dr
- `datagouv__4-2-millions-de-prestations-daide-sociale-atttribuees-par-les-departements-en-2014` [erreur] : toutes les ressources en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er942.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.dr
- `datagouv__55-ans-de-diversification-des-financements-de-la-protection-sociale` [erreur] : toutes les ressources en echec, ex. http://drees.social-sante.gouv.fr/IMG/xls/er_1002.xls injoignable apres 6 tentatives : ConnectionError: HTTPConnectionPool(h
- `datagouv__97-000-jeunes-en-grande-precarite-beneficient-du-fonds-daide-aux-jeunes-en-2013` [erreur] : toutes les ressources en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er903.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.dr
- `datagouv__aide-administrative-du-pole-social-de-digne-les-bains-de-2012-a-2015` [erreur] : toutes les ressources en echec, ex. https://trouver.datasud.fr/dataset/7f1f3c96-6049-4298-84ae-aee578fe60e3/resource/3b60ab0a-c572-4cef-a9a8-d115d95dde88/downlo
- `datagouv__aide-fsu-du-pole-social-de-digne-les-bains-de-2010-a-2017` [erreur] : toutes les ressources en echec, ex. https://trouver.datasud.fr/dataset/f55864b3-26ae-4e22-a227-af0eb0733b8f/resource/32e47aa1-dac3-4947-91e1-5bf055d10148/downlo
- `datagouv__aide-rsa-du-ccas-de-digne-les-bains-de-2010-a-2016` [erreur] : toutes les ressources en echec, ex. https://trouver.datasud.fr/dataset/ba0ad1eb-7c01-43b4-ae43-fd2070a2aa3e/resource/70a799e1-e232-4bab-94c9-4a7bf984f504/downlo
- `datagouv__aide-sociale-a-lhebergement-et-allocation-personnalisee-dautonomie-en-2011-profil-des-beneficiaires-en-etablis` [erreur] : toutes les ressources en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er909.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.dr
- `datagouv__aides-aux-entreprises-de-la-region-des-pays-de-la-loire-2017` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://Data.paysdelaloire.fr/explore/dataset/234400034_040-002_dispositifs-economiques-de-la-region-des-pays-d
- `datagouv__aides-communes76-arr-2017-2019-1` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::aides-communes76-arr-2017-2019.geojson?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%
- `datagouv__aides-communes76-dispositif-2017-2019-1` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::aides-communes76-dispositif-2017-2019.csv?where=1=1 (HTTP 500) (budget 150 s)
- `datagouv__aides-entreprises` [delai_depasse] : budget de temps epuise sur https://data.aides-entreprises.fr/files/profils.csv (ProxyError: HTTPSConnectionPool(host='data.aides-entreprises.fr', port=443): Max
- `datagouv__aides-financieres-et-en-ingenierie-disponibles-pour-les-collectivites-territoriales-et-leurs-partenaires-locau` [erreur] : HTTP 404 sur https://aides-territoires-prod.s3.fr-par.scw.cloud/aides-territoires-prod/aids/all-aids.json : <Error><Code>NoSuchBucket</Code><Message>The specifi
- `datagouv__aides-hebergement-en-etablissement-personnes-agees-hepa-par-epci-cd76-2022` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::hepa-depenses-et-beneficiaires-par-epci-cd76-2022.zip?outSR=%7B%22latestWkid%22%3A
- `datagouv__aides-hebergement-personnes-handicapees-heph-par-canton-cd76-2022` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::heph-depenses-et-beneficiaires-par-canton-cd76-2022.zip?outSR=%7B%22latestWkid%22%
- `datagouv__aides-hebergement-personnes-handicapees-heph-par-epci-cd76-2022` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::heph-depenses-et-beneficiaires-par-epci-cd76-2022.zip?outSR=%7B%22latestWkid%22%3A
- `datagouv__aides-personalisees-autonomie-a-domicile-apad-canton76-2022` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::apad-depenses-et-beneficiaires-canton76-2022.zip?outSR=%7B%22latestWkid%22%3A3857%
- `datagouv__aides-personalisees-autonomie-a-domicile-apad-epci76-2022` [delai_depasse] : budget de temps epuise sur https://www.opendata76.fr/datasets/seine-maritime::apad-depenses-et-beneficiaires-epci76-2022.zip?outSR=%7B%22latestWkid%22%3A3857%2C
- `datagouv__aides-sociales-du-ccas-de-digne-les-bains` [erreur] : https://trouver.datasud.fr/dataset/b5387908-0dd9-4f74-a581-2b8bb7efdbec/resource/5a6dd952-3d3a-4536-aa90-266cbd3ff322/download/digne-activite-sociale-ccas-2010-
- `datagouv__arret-compte-de-gestion-2021-budget-assainissement-1` [erreur] : aucune ressource telechargeable correspondante
- `datagouv__atlas-fiscal` [erreur] : HTTP 404 sur https://www.impots.gouv.fr/portail/files/media/stats/atlas_fiscal_fichedescriptive_6645.pdf : <!DOCTYPE html> <html lang="fr" dir="ltr" prefix="con
- `datagouv__attribution-des-marches-publics` [delai_depasse] : budget de temps epuise sur https://api-data.cacl-guyane.fr/v1/cayenne-marches-publics?format=xls (SSLError: HTTPSConnectionPool(host='api-data.cacl-guyane.fr', 
- `datagouv__balances-comptables-des-groupements-a-fiscalite-propre-2019` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://data.metropole-dijon.fr/api/explore/v2.1/catalog/datasets/balances-comptables-de-dijon-metropole-depuis
- `datagouv__blois-subventions-2020-votees-au-budget-primitif` [erreur] : aucune ressource telechargeable correspondante
- `datagouv__bp-2010-budget-principal-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2010_Budget_Principal.xls
- `datagouv__bp-2010-budgets-annexes-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2010_Budgets_Annexes.xls
- `datagouv__bp-2010-subventions-aux-associations-rm` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2010_Subv_excep
- `datagouv__bp-2011-budget-principal-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2011_Budget_Principal.xls
- `datagouv__bp-2011-budgets-annexes-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2011_Budget_Annexes.xls
- `datagouv__bp-2011-subventions-aux-associations-rm` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2011_Subvention
- `datagouv__bp-2012-budget-principal-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/BP2012/BP_2012_Open_DATA_Budget_Principal.xls
- `datagouv__bp-2012-budgets-annexes-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/BP2012/BP_2012_Open_DATA_Budget_Annexes.xls
- `datagouv__bp-2012-subventions-aux-associations-rm` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/BP2012/BP_2012_Open_DATA_Subvention
- `datagouv__bp-2013-budget-annexes-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/budget/bp2013/BP_2013_Open_DATA_Budget_Annexes.xls
- `datagouv__bp-2013-budget-principal-rm` [erreur] : acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/budget/bp2013/BP_2013_Open_DATA_Budget_Principal.xls
- `datagouv__bp-2013-subventions-aux-associations-rm` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/budget/bp2013/BP_2013_Open_DATA_Sub
- `datagouv__budget-2015-par-politique-publique1` [erreur] : toutes les ressources en echec, ex. https://datacat.datalocale.fr/file/421808/raw/DownloadCsv%3Fcontainer%3Ddatabordeaux%26entitySet%3Dbudge injoignable apres 6
- `datagouv__budget-assainissement-2017` [delai_depasse] : budget de temps epuise sur http://data.coeurcotefleurie.org/dataset/e85fc443-1481-4faf-8892-912ade5f7bc7/resource/c6edf41f-b57c-44f4-8f7b-227543a85ac8/download/
- `datagouv__budget-assainissement-2018` [delai_depasse] : budget de temps epuise sur http://data.coeurcotefleurie.org/dataset/ab06f5ee-3cce-4d9c-a72d-dfefbe892c5c/resource/27e3221c-5bc1-4255-ba3b-eba1085b8a41/download/
- `datagouv__budget-compte-administratif-sictiam` [delai_depasse] : budget de temps epuise sur https://opendata.sictiam.fr/dataset/19f93cd5-021c-46a4-930b-a8b88c209acc/resource/7b575c43-d676-4c9c-91ad-366ebad6b74d/download/budge
- `datagouv__budget-comptes-publics` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://numerique.brocaslesforges.fr/explore/dataset/comptes-des-collectivites/download?format=csv&timezone=Eur
- `datagouv__budget-dotation-globale-fonctionnement` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://numerique.brocaslesforges.fr/explore/dataset/dotation-globale-de-fonctionnement-des-communes/download?f
- `datagouv__budget-eau-2016` [delai_depasse] : budget de temps epuise sur http://data.coeurcotefleurie.org/dataset/1d6065cd-3410-4297-bfc9-cb274780c284/resource/f111bca8-b4d6-4daa-b3c1-b03a302e6c86/download/
- `datagouv__budget-investissement-public-local` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://numerique.brocaslesforges.fr/explore/dataset/investissement-public-local/download?format=csv&timezone=E
- `datagouv__budget-par-chapitres-et-comptes-par-fonction-oise` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 403 sur http://opendata.oise.fr/fileadmin/data/PFA/2-donnee1-budget-fonction-bp2013.pdf
- `datagouv__budget-par-chapitres-et-comptes-par-nature-oise` [erreur] : toutes les ressources en echec, ex. acces refuse HTTP 403 sur http://opendata.oise.fr/fileadmin/data/PFA/1-donnee2-budget-nature-ca2012.pdf
- `datagouv__budget-previsionnel-budget-principal-donnees-budgetaires-du-departement-de-la-gironde-1` [erreur] : toutes les ressources en echec, ex. https://datacat.datalocale.fr/distribution/2172479/raw/BP2016BP.xml injoignable apres 6 tentatives : ProxyError: HTTPSConnec
- `datagouv__budget-primitif-1` [erreur] : aucune ressource telechargeable correspondante
- `datagouv__budget-primitif-2` [erreur] : aucune ressource telechargeable correspondante
- `datagouv__budget-primitif-2014-de-la-ville-du-havre` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/145/BUDGET_PRIMITIF_2014/json (SSLError: HTTPSConnectionPool(host='data.lehavr
- `datagouv__budget-primitif-2015` [erreur] : toutes les ressources en echec, ex. https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2015/exports/csv injoignable apres 6 tentatives : Con
- `datagouv__budget-primitif-2015-de-la-ville-dissy-les-moulineaux-2` [erreur] : HTTP 404 sur http://data.issy.com/explore/dataset/bp2015/?tab=export&sort=section :  <!DOCTYPE html> <html lang="fr-FR" >     <head>                    <title>P
- `datagouv__budget-primitif-2015-de-la-ville-du-havre` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/146/BUDGET_PRIMITIF_2015/json (SSLError: HTTPSConnectionPool(host='data.lehavr
- `datagouv__budget-primitif-2016-1` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2016/exports/json (ConnectionError: ('Connection aborted.', Co
- `datagouv__budget-primitif-2016-de-la-ville-du-havre` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/147/BUDGET_PRIMITIF_2016/json (SSLError: HTTPSConnectionPool(host='data.lehavr
- `datagouv__budget-primitif-2016-de-lagglomeration-havraise` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/162/BUDGET_PRIMITIF_CODAH_2016/json (SSLError: HTTPSConnectionPool(host='data.
- `datagouv__budget-primitif-2017-4` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2017/exports/json (ConnectionError: ('Connection aborted.', Co
- `datagouv__budget-primitif-2017-de-lagglomeration-havraise` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/5572/BUDGET_PRIMITIF_CODAH_2017/json (SSLError: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2017-ville-angers-1` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://data.paysdelaloire.fr/explore/dataset/bp-2017-angers/download?format=csv&timezone=Europe/Berlin&use_lab
- `datagouv__budget-primitif-2018-1` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2018/exports/json (ReadTimeout: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2018-de-la-commune-docteville-sur-mer-1` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/17253/BUDGET_PRIMITIF_481_2018/json (SSLError: HTTPSConnectionPool(host='data.
- `datagouv__budget-primitif-2018-de-la-ville-du-havre` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/67251/BUDGET_PRIMITIF_2018/json (SSLError: HTTPSConnectionPool(host='data.leha
- `datagouv__budget-primitif-2018-de-lagglomeration-havraise` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/5573/BUDGET_PRIMITIF_CODAH_2018/json (SSLError: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2019` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2019/exports/json (ReadTimeout: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2019-de-la-communaute-urbaine-le-havre-seine-metropole` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/48405/BUDGET_PRIMITIF_LHSM_2019/json (SSLError: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2019-de-la-ville-du-havre` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/67252/BUDGET_PRIMITIF_2019/json (SSLError: HTTPSConnectionPool(host='data.leha
- `datagouv__budget-primitif-2020-2` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2020/exports/json (ConnectionError: ('Connection aborted.', Co
- `datagouv__budget-primitif-2020-de-la-communaute-urbaine-le-havre-seine-metropole` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/67250/BUDGET_PRIMITIF_LHSM_2020/json (SSLError: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2021` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2021/exports/json (ConnectionError: ('Connection aborted.', Co
- `datagouv__budget-primitif-2021-de-la-communaute-urbaine-le-havre-seine-metropole` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/84201/BUDGET_PRIMITIF_LHSM_2021/json (SSLError: HTTPSConnectionPool(host='data
- `datagouv__budget-primitif-2021-du-budget-principal` [erreur] : toutes les ressources en echec, ex. HTTP 404 sur https://porto-vecchio.opendatasoft.com/api/explore/v2.1/catalog/datasets/budget-primitif1/exports/csv?use_label
- `datagouv__budget-primitif-2022` [delai_depasse] : budget de temps epuise sur https://data.agen.fr/api/explore/v2.1/catalog/datasets/budget-primitif-2022/exports/json (ConnectionError: ('Connection aborted.', Co
- `datagouv__budget-primitif-2022-de-la-communaute-urbaine-le-havre-seine-metropole` [delai_depasse] : budget de temps epuise sur https://data.lehavreseinemetropole.fr/api/v1/file/data/84238/BUDGET_PRIMITIF_LHSM_2022/json (SSLError: HTTPSConnectionPool(host='data
- ... et 249 autres (detail dans le manifeste)

## Jeux sans fichier telechargeable (133)

Jeux catalogues mais vides ou publies seulement en page web / API : `datagouv__1-asso-territoire-zero-chomeur-attribution-dune-subvention-2022`, `datagouv__agreste-depenses-pour-proteger-l-environnement-dans-les-industries-agroalimentaires`, `datagouv__aide-aux-collegiens-acri-par-epci-cd76-2022a2025-20260903-metadonnees`, `datagouv__aide-en-ligne`, `datagouv__aides-aux-petits-investissements-agricoles-au-12-03-2024-1`, `datagouv__annexe-budget-primitif-assainissement-2018-3`, `datagouv__annexe-budget-primitif-la-pepiniere-2018-2`, `datagouv__arret-compte-de-gestion-2021-budget-general-1`, `datagouv__assainissement-budget-primitif-2022-1`, `datagouv__association-dynactive-subvention-2022-pour-la-journee-des-entreprises-2`, `datagouv__balances-comptables-2015-des-budgets-principaux-et-annexes-des-groupements-de-communes-a-fisclaite-propre`, `datagouv__budget-assainissement-2020-1`, `datagouv__budget-office-de-tourisme-subvention-du-budget-principal-2019-1`, `datagouv__budget-office-tourisme-2020-1`, `datagouv__budget-oti-subvention-du-budget-principal-2020-2`, `datagouv__budget-pepiniere-2020-1`, `datagouv__budget-primitif-2018-9`, `datagouv__budget-primitif-2022-5`, `datagouv__budget-primitif-2023-4`, `datagouv__budget-principal-2020-1`, `datagouv__ca-2019-budget-assainissement-2020-2`, `datagouv__carte-aides-a-l-investissement-aux-communes-et-intercommunalites-cd-2017-2024`, `datagouv__carte-aides-a-l-investissement-aux-communes-et-intercommunalites-par-type-d-aide-cd-2017-2023-jllt24`, `datagouv__carte-aides-a-l-investissement-des-communes-et-intercommunalites-par-montant-cd76-2017-2024`, `datagouv__carte-aides-aux-collegiens-acri-cd76-epci-2022a2025-20260903`, `datagouv__carte-aides-aux-collegiens-acri-par-canton-cd76-2022-2025-20260903`, `datagouv__carte-aides-aux-petits-investissements-2016-2024`, `datagouv__carte-delegation-aides-a-la-pierre-cd76-2023`, `datagouv__carte-des-communes-eligibles-a-l-aide-en-ingenierie-r3232-1-cd76-220503`, `datagouv__carte-subventions-cd76-2008a23`, `datagouv__carte-titulaires-marches-public-2018a2026`, `datagouv__ceevo-deliberation-octroi-subvention-cotisation-2019-2`, `datagouv__compte-administratif-2014-depenses-du-budget-ports-de-plaisance-1`, `datagouv__compte-administratif-2017-3`, `datagouv__compte-administratif-2018-3`, `datagouv__compte-administratif-2019-2`, `datagouv__compte-administratif-2020-2`, `datagouv__compte-administratif-2021-2`, `datagouv__compte-administratif-2022-14k-1`, `datagouv__compte-administratif-2022-2`, `datagouv__compte-administratif-2022-assainissement-1`, `datagouv__compte-administratif-2022-office-tourisme-1`, `datagouv__compte-administratif-2022-plaine-vallee-1`, `datagouv__compte-de-resultat-consolide-du-groupe-edf`, `datagouv__compte-gestion-2019-budget-oti-1`, `datagouv__compte-gestion-2021-budget-oti-2022-1`, `datagouv__compte-rendu-conseil-de-communaute-du-09-02-2022-1`, `datagouv__compte-rendu-decisions-n2019-47-a-2019-68-2019-2`, `datagouv__compte-rendu-des-decisions-avril-2019-3`, `datagouv__compte-rendu-des-deliberations-prises-au-bureau-communautaire`, `datagouv__comptes-administratifs-caln-2020`, `datagouv__comptes-administratifs-caln-2021`, `datagouv__comptes-administratifs-caln-2022`, `datagouv__comptes-de-campagne-elections-departementales-des-22-et-29-mars-2015`, `datagouv__comptes-de-campagnes-elections-partielles-pour-lannee-2016`, `datagouv__convention-fmaji-subvention-2020-1`, `datagouv__delib-arret-compte-de-gestion-2019-budget-assainissement-1`, `datagouv__delib-arret-compte-de-gestion-2019-budget-general-2`, `datagouv__deliberation-arret-compte-de-gestion-2018-budget-assainissement-2019-2`, `datagouv__deliberation-arret-compte-de-gestion-2018-budget-pepiniere-2019-3` ...

## Sources partielles (298) : ressources en echec, les autres collectees

- `aides_fonds_solidarite` : 10 ressource(s) en echec, ex. acces refuse HTTP 403 sur https://github.com/etalab/dashboard-aides-entreprises/blob/master/published-data/fonds-solidarite-volet-1-regional-naf.xlsx?
- `datagouv__1-2-million-de-travailleurs-sociaux-en-2011` : 2 ressource(s) en echec, ex. http://www.drees.sante.gouv.fr/IMG/pdf/er893.pdf injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.drees.sante.gouv.fr', port=4
- `datagouv__1695047341709-1-1` : 1 ressource(s) en echec, ex. https://grandestprod.data4citizen.com/data4citizen/sites/default/files/dataset/2023/09/29/c63f0025-ea5a-4d83-afef-e378daa19ed9/conseil_departemental_m
- `datagouv__1695387641865-1` : 9 ressource(s) en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695387641865-11695387641865-1/conseil-departemental-meuse-2018-PRINCIPAL-xml.zip : {"timestamp
- `datagouv__1695387722855-1` : 2 ressource(s) en echec, ex. https://grandestprod.data4citizen.com/data4citizen/sites/default/files/dataset/2023/09/23/a3ff8a67-e09b-4f6e-b168-3e8c40d1f16d/conseil_departemental_m
- `datagouv__1695388365181-1` : 18 ressource(s) en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388365181-11695388365181-1/conseil-departemental-meuse-2020-PRINCIPAL-csv.zip : {"timestamp
- `datagouv__1695388552745-2` : 18 ressource(s) en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388552745-21695388552745-2/conseil-departemental-meuse-2021-PRINCIPAL.ods : {"timestamp":"2
- `datagouv__1695388704140-3` : 18 ressource(s) en echec, ex. HTTP 404 sur https://www.datagrandest.fr/metadata/cd55/1695388704140-31695388704140-3/conseil-departemental-meuse-2022-PRINCIPAL.ods : {"timestamp":"2
- `datagouv__3-8-millions-de-prestations-daide-sociale-attribuees-par-les-departements-en-2013` : 2 ressource(s) en echec, ex. http://www.drees.sante.gouv.fr/IMG/pdf/er900.pdf injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.drees.sante.gouv.fr', port=4
- `datagouv__4-2-millions-de-prestations-daide-sociale-atttribuees-par-les-departements-en-2014` : 2 ressource(s) en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er942.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.drees.sante.gouv.fr', port=4
- `datagouv__55-ans-de-diversification-des-financements-de-la-protection-sociale` : 2 ressource(s) en echec, ex. http://drees.social-sante.gouv.fr/IMG/xls/er_1002.xls injoignable apres 6 tentatives : ConnectionError: HTTPConnectionPool(host='drees.social-sante.go
- `datagouv__97-000-jeunes-en-grande-precarite-beneficient-du-fonds-daide-aux-jeunes-en-2013` : 2 ressource(s) en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er903.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.drees.sante.gouv.fr', port=4
- `datagouv__aide-administrative-du-pole-social-de-digne-les-bains-de-2012-a-2015` : 2 ressource(s) en echec, ex. https://trouver.datasud.fr/dataset/7f1f3c96-6049-4298-84ae-aee578fe60e3/resource/3b60ab0a-c572-4cef-a9a8-d115d95dde88/download/digne-aide-administrati
- `datagouv__aide-aux-collegiens-acri-par-canton-cd76-2022a2023-20240729` : 4 ressource(s) en echec, ex. acces refuse HTTP 403 sur https://www.opendata76.fr/api/download/v1/items/692a064cb8af4b6a96b4df095293bee9/csv?layers=0
- `datagouv__aide-educative-budgetaire-renforcee-aebr-cantons-cd76-2017a2023-20240729` : 4 ressource(s) en echec, ex. acces refuse HTTP 403 sur https://www.opendata76.fr/api/download/v1/items/da453335f97440e0b63a7f078b445b32/csv?layers=0
- `datagouv__aide-fsu-du-pole-social-de-digne-les-bains-de-2010-a-2017` : 2 ressource(s) en echec, ex. https://trouver.datasud.fr/dataset/f55864b3-26ae-4e22-a227-af0eb0733b8f/resource/32e47aa1-dac3-4947-91e1-5bf055d10148/download/digne-aide-fsu-pole-soc
- `datagouv__aide-menagere-pa-ph-depenses-et-benef-cantons-cd76-2022` : 8 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::aide-menagere-pa-ph-depenses-et-benef-cantons-cd76-2022.csv?where=1=1&outSR=%7B%22latestWkid%22%3A3
- `datagouv__aide-menagere-pa-ph-depenses-et-benef-epci-cd76-2022` : 12 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::aide-menagere-pa-ph-depenses-et-benef-epci-cd76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid
- `datagouv__aide-rsa-du-ccas-de-digne-les-bains-de-2010-a-2016` : 2 ressource(s) en echec, ex. https://trouver.datasud.fr/dataset/ba0ad1eb-7c01-43b4-ae43-fd2070a2aa3e/resource/70a799e1-e232-4bab-94c9-4a7bf984f504/download/digne-rsa-ccas-2010-201
- `datagouv__aide-sociale-a-lhebergement-et-allocation-personnalisee-dautonomie-en-2011-profil-des-beneficiaires-en-etablis` : 2 ressource(s) en echec, ex. http://www.drees.sante.gouv.fr/IMG/xls/er909.xls injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='www.drees.sante.gouv.fr', port=4
- `datagouv__aides-a-l-investissement-aux-communes-et-intercommunalites-cd76-2017-2023-juin2024` : 4 ressource(s) en echec, ex. HTTP 400 sur https://www.opendata76.fr/api/download/v1/items/3c9437d319fe47178be42cc8b1bb92a5/csv?layers=0 : {"message":"Item does not exist or is ina
- `datagouv__aides-aux-entreprises-de-la-region-des-pays-de-la-loire-2017` : 8 ressource(s) en echec, ex. HTTP 404 sur https://Data.paysdelaloire.fr/explore/dataset/234400034_040-002_dispositifs-economiques-de-la-region-des-pays-de-la-loire/download?format
- `datagouv__aides-communes76-arr-2017-2019-1` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::aides-communes76-arr-2017-2019.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A102100%7D injoig
- `datagouv__aides-communes76-dispositif-2017-2019-1` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::aides-communes76-dispositif-2017-2019.geojson injoignable apres 6 tentatives : HTTP 500
- `datagouv__aides-entreprises` : 2 ressource(s) en echec, ex. https://data.aides-entreprises.fr/files/aides.csv injoignable apres 6 tentatives : ProxyError: HTTPSConnectionPool(host='data.aides-entreprises.fr', p
- `datagouv__aides-hebergement-en-etablissement-personnes-agees-hepa-par-epci-cd76-2022` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::hepa-depenses-et-beneficiaires-par-epci-cd76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22
- `datagouv__aides-hebergement-personnes-handicapees-heph-par-canton-cd76-2022` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::heph-depenses-et-beneficiaires-par-canton-cd76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%
- `datagouv__aides-hebergement-personnes-handicapees-heph-par-epci-cd76-2022` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::heph-depenses-et-beneficiaires-par-epci-cd76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22
- `datagouv__aides-personalisees-autonomie-a-domicile-apad-canton76-2022` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::apad-depenses-et-beneficiaires-canton76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A10
- `datagouv__aides-personalisees-autonomie-a-domicile-apad-epci76-2022` : 2 ressource(s) en echec, ex. https://www.opendata76.fr/datasets/seine-maritime::apad-depenses-et-beneficiaires-epci76-2022.csv?outSR=%7B%22latestWkid%22%3A3857%2C%22wkid%22%3A1021
- `datagouv__annexe-au-budget-primitif-2017-du-departement-de-vaucluse` : 1 ressource(s) en echec, ex. HTTP 404 sur https://www.datasud.fr/fr/dataset/datasets/231/resource/309/download/ : {"detail":"No ResourceDataset matches the given query."}
- `datagouv__apaa-domicile-depenses-et-beneficiaires-par-gir-par-cantons-2023` : 4 ressource(s) en echec, ex. HTTP 400 sur https://www.opendata76.fr/api/download/v1/items/dfb424c1f60446ad9839c0caedc53a8d/csv?layers=0 : {"message":"Item does not exist or is ina
- `datagouv__attribution-des-marches-publics` : 2 ressource(s) en echec, ex. https://api-data.cacl-guyane.fr/v1/cayenne-marches-publics?format=csv injoignable apres 6 tentatives : SSLError: HTTPSConnectionPool(host='api-data.ca
- `datagouv__balances-comptables-des-groupements-a-fiscalite-propre-2019` : 2 ressource(s) en echec, ex. HTTP 404 sur https://data.metropole-dijon.fr/api/explore/v2.1/catalog/datasets/balances-comptables-de-dijon-metropole-depuis-2010/exports/csv?use_labe
- `datagouv__boamp` : 1 ressource(s) en echec, ex. HTTP 404 sur https://echanges.dila.gouv.fr/OPENDATA/BOAMP/2025/ : <!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>404 Not Found
- `datagouv__bp-2010-subventions-aux-associations-rm` : 3 ressource(s) en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2010_Subv_exception.xls
- `datagouv__bp-2011-subventions-aux-associations-rm` : 3 ressource(s) en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/data_sig/uploads/BP_2011_Subventions_exceptionnelles.xls
- `datagouv__bp-2012-subventions-aux-associations-rm` : 3 ressource(s) en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/BP2012/BP_2012_Open_DATA_Subventions_exceptionnelles.xls
- `datagouv__bp-2013-subventions-aux-associations-rm` : 3 ressource(s) en echec, ex. acces refuse HTTP 401 sur http://www.data.rennes-metropole.fr/fileadmin/user_upload/data/budget/bp2013/BP_2013_Open_DATA_Subventions_exceptionnelles.x
- `datagouv__budget-2015-par-politique-publique1` : 2 ressource(s) en echec, ex. https://datacat.datalocale.fr/file/421808/raw/DownloadCsv%3Fcontainer%3Ddatabordeaux%26entitySet%3Dbudge injoignable apres 6 tentatives : ProxyError: 

## Sources avec donnees de personnes physiques (279)

Publiees en open data officiel, stockees sous `data/lake/_restreint/`. Collecte autorisee, affichage nominatif interdit.

- `aides_cir_organismes_agrees` (aides_entreprises, ok, 1.6 Mo) : Organismes agrees au credit d'impot recherche
- `aides_subventions_agricoles` (aides_entreprises, ok, 0.2 Mo) : Subventions agricoles superieures a 23 000 euros (ressource la plus recente)
- `benef_aides_minimis` (beneficiaires, ok, 1.0 Mo) : Aides de minimis aux entreprises
- `benef_decp` (beneficiaires, ok, 276.8 Mo) : Marches publics (DECP consolidees)
- `cdc__droit-individuel-a-la-formation-dif-des-elus-locaux` (collectivites, ok, 1.2 Mo) : Droit individuel à la formation (DIF) des élus locaux
- `cdc__moncompteelu-formations-elus` (etat, ok, 2.3 Mo) : Moncompteelu - Les formations réalisées par les élus
- `datagouv__15079-verification-des-titres-de-sejour-par-les-employeurs` (politique, ok, 0.0 Mo) : 15079 - Vérification des titres de séjour par les employeurs
- `datagouv__1900-2020-comptes-de-gestion-commune-de-jouarre` (collectivites, ok, 0.2 Mo) : 1900 - 2020 Comptes de Gestion Commune de Jouarre
- `datagouv__2014-62-verification-des-titres-de-sejour-par-les-employeurs-metropole` (politique, ok, 0.0 Mo) : 2014-62 - Vérification des titres de séjour par les employeurs (métropole)
- `datagouv__acco-accords-dentreprise` (beneficiaires, ok, 0.2 Mo) : ACCO : Accords d’entreprise
- `datagouv__actes-budgetaires-1` (decisions, ok, 25.9 Mo) : Actes Budgétaires
- `datagouv__adresses-des-debits-de-tabac` (collectivites, ok, 0.3 Mo) :  Adresses des débits de tabac
- `datagouv__aide-installation-des-jeunes-agriculteurs-annees-2013-et-2014` (beneficiaires, ok, 0.0 Mo) : Aide installation des jeunes agriculteurs - Années 2013 et 2014
- `datagouv__aides-communes76-arr-2017-2019-1` (beneficiaires, delai_depasse, 0.0 Mo) : Aides communes76 Arr 2017 2019
- `datagouv__apb-et-acces-a-lenseignement-superieur-un-dispositif-conteste-a-reformer` (politique, ok, 0.0 Mo) : APB et accès à l’enseignement supérieur : un dispositif contesté à réformer
- `datagouv__bodacc` (beneficiaires, ok, 1.4 Mo) : BODACC
- `datagouv__budget-des-depenses-de-personnel-de-la-region-ile-de-france` (collectivites, ok, 0.0 Mo) : Budget des dépenses de personnel de la Région Île-de-France
- `datagouv__budget-primitif-de-la-communaute-urbaine-de-bordeaux1` (etat, ok, 0.4 Mo) : budget primitif de la communauté urbaine de Bordeaux
- `datagouv__budgets-primitif-du-departement-de-la-gironde` (collectivites, delai_depasse, 0.0 Mo) : Budgets primitif du département de la Gironde
- `datagouv__budgets-primitif-du-departement-de-la-gironde-2` (collectivites, delai_depasse, 0.0 Mo) : Budgets primitif du département de la Gironde
- `datagouv__budgets-primitif-du-departement-de-la-gironde-3` (collectivites, delai_depasse, 0.0 Mo) : Budgets primitif du département de la Gironde
- `datagouv__chiffres-officiels-de-la-societe-impot-sur-les-societes-dividendes-creation-sci-et-holding` (fiscalite, ok, 0.0 Mo) : Chiffres officiels de la société : impôt sur les sociétés, dividendes, création, SCI et holding
- `datagouv__circonscritions-legislatives-74-2015` (decisions, ok, 30.6 Mo) : Circonscritions législatives 74 - 2015
- `datagouv__compte-de-campagne-elections-partielles-pour-lannee-2016` (politique, erreur, 0.0 Mo) : Compte de campagne - Elections partielles pour l'année 2016
- `datagouv__comptes-administratifs-du-departement-de-la-gironde` (collectivites, delai_depasse, 0.0 Mo) : Comptes administratifs du Département de la Gironde
- `datagouv__comptes-administratifs-du-departement-de-la-gironde-1` (collectivites, delai_depasse, 0.0 Mo) : Comptes administratifs du Département de la Gironde
- `datagouv__comptes-administratifs-du-departement-de-la-gironde-2` (collectivites, delai_depasse, 0.0 Mo) : Comptes administratifs du Département de la Gironde
- `datagouv__comptes-de-campagne-election-des-conseillers-a-lassemblee-de-corse-generale` (politique, ok, 0.0 Mo) : Comptes de campagne – Élection des conseillers à l’Assemblée de Corse générale
- `datagouv__comptes-de-campagne-election-des-representants-au-parlement-europeen-des-8-et-9-juin-2024` (politique, ok, 0.0 Mo) : Comptes de campagne – Élection des représentants au Parlement européen des 8 et 9 juin 2024
- `datagouv__comptes-de-campagne-election-des-representants-au-parlement-europeen-du-25-mai-2014` (politique, ok, 0.0 Mo) : Comptes de campagne – Election des représentants au Parlement européen du 25 mai 2014
- `datagouv__comptes-de-campagne-election-des-representants-au-parlement-europeen-du-26-mai-2019` (politique, ok, 0.0 Mo) : Comptes de campagne – Élection des représentants au Parlement européen du 26 mai 2019
- `datagouv__comptes-de-campagne-elections-aux-elections-departementales-des-20-et-27-juin-2021` (politique, ok, 2.8 Mo) : Comptes de campagne – Élections aux élections départementales des 20 et 27 juin 2021
- `datagouv__comptes-de-campagne-elections-aux-elections-regionales-et-des-conseillers-aux-assemblees-de-corse-de-guyane-et` (politique, ok, 0.1 Mo) : Comptes de campagne – Élections aux élections régionales et des conseillers aux assemblées de Corse, de Guyane et de Martinique des 20 et 27 juin 2021
- `datagouv__comptes-de-campagne-elections-departementales-des-22-et-29-mars-2015` (politique, sans_ressource, 0.0 Mo) : Comptes de campagne – Elections départementales des 22 et 29 mars 2015
- `datagouv__comptes-de-campagne-elections-departementales-des-22-et-29-mars-2015-1` (politique, ok, 1.6 Mo) : Comptes de campagne – Elections départementales des 22 et 29 mars 2015
- `datagouv__comptes-de-campagne-elections-legislatives-des-11-et-18-juin-2017` (politique, ok, 0.9 Mo) : Comptes de campagne – Élections législatives des 11 et 18 juin 2017
- `datagouv__comptes-de-campagne-elections-legislatives-generales-des-12-et-19-juin-2022` (politique, ok, 1.8 Mo) : Comptes de campagne – Élections législatives générales des 12 et 19 juin 2022
- `datagouv__comptes-de-campagne-elections-municipales-des-23-et-30-mars-2014` (politique, ok, 0.6 Mo) : Comptes de campagne - Elections municipales des 23 et 30 mars 2014
- `datagouv__comptes-de-campagne-elections-municipales-generales-des-15-mars-et-28-juin-2020` (politique, ok, 1.5 Mo) : Comptes de campagne – Élections municipales générales des 15 mars et 28 juin 2020
- `datagouv__comptes-de-campagne-elections-partielles-pour-lannee-2016` (politique, ok, 0.0 Mo) : Comptes de campagne - élections partielles pour l'année 2016 
- `datagouv__comptes-de-campagne-elections-partielles-pour-lannee-2016-1` (politique, ok, 0.0 Mo) : Comptes de campagne - Elections partielles pour l'année 2016
- `datagouv__comptes-de-campagne-elections-partielles-pour-lannee-2016-2` (politique, ok, 0.0 Mo) : Comptes de campagne - Elections partielles pour l'année 2016
- `datagouv__comptes-de-campagne-elections-senatoriales-du-24-septembre-2017` (politique, ok, 0.5 Mo) : Comptes de campagne - Elections sénatoriales du 24 septembre 2017
- `datagouv__comptes-de-campagne-elections-senatoriales-du-28-septembre-2014` (politique, ok, 0.1 Mo) : Comptes de campagne - Elections sénatoriales du 28 septembre 2014
- `datagouv__comptes-de-campagne-elections-senatoriales-generales-du-24-septembre-2023` (politique, ok, 0.1 Mo) : Comptes de campagne – Élections sénatoriales générales du 24 septembre 2023
- `datagouv__comptes-de-campagne-elections-territoriales-de-saint-martin-et-saint-barthelemy-des-20-et-27-mars-2022` (politique, ok, 0.0 Mo) : Comptes de campagne – Élections territoriales de Saint-Martin et Saint-Barthélemy des 20 et 27 mars 2022
- `datagouv__comptes-de-campagnes-elections-partielles-pour-lannee-2016` (politique, sans_ressource, 0.0 Mo) : Comptes de campagnes - Elections partielles pour l'année 2016
- `datagouv__comptes-de-sailly-lez-lannoy-2014-2021` (decisions, ok, 0.1 Mo) : Comptes de Sailly-Lez-Lannoy 2014-2021
- `datagouv__conseils-municipaux-2026` (decisions, ok, 114.1 Mo) : Conseils Municipaux 2026
- `datagouv__conventions-de-subvention-aux-associations-exercice-2020` (beneficiaires, ok, 0.0 Mo) : Conventions de subvention aux associations - Exercice 2020
- `datagouv__deliberations-15` (decisions, ok, 131.1 Mo) : DELIBERATIONS
- `datagouv__deliberations-16` (decisions, ok, 34.9 Mo) : Délibérations
- `datagouv__deliberations-2019-du-departement-de-la-dordogne` (decisions, ok, 0.4 Mo) : Délibérations 2019 du Département de la Dordogne
- `datagouv__deliberations-23` (decisions, ok, 0.4 Mo) : Délibérations
- `datagouv__deliberations-de-la-commune-de-marseillan` (decisions, ok, 0.1 Mo) : Délibérations de la commune de Marseillan
- `datagouv__deliberations-de-la-ville-de-saint-etienne` (decisions, ok, 7.7 Mo) : Délibérations de la ville de Saint-Etienne
- `datagouv__deliberations-de-la-ville-du-pre-saint-gervais-sur-la-periode-2003-2021` (decisions, ok, 0.4 Mo) : Délibérations de la ville du Pré Saint-Gervais sur la période 2003 - 2021
- `datagouv__deliberations-de-saint-etienne-metropole` (decisions, ok, 8.0 Mo) : Délibérations de Saint-Etienne Métropole
- `datagouv__deliberations-decisions-et-arretes-de-brest-metropole-et-de-la-ville-de-brest` (decisions, ok, 19.3 Mo) : Délibérations, décisions et arrêtés de Brest métropole et de la Ville de Brest
- `datagouv__deliberations-du-ccas` (decisions, ok, 74.0 Mo) : Délibérations du CCAS
- `datagouv__deliberations-du-ccas-de-la-ville-de-brest` (decisions, ok, 0.4 Mo) : Délibérations du CCAS de la Ville de Brest
- `datagouv__deliberations-du-conseil-departemental-du-cher-et-de-la-commission-permanente` (decisions, ok, 0.4 Mo) : Délibérations du conseil départemental du Cher et de la commission permanente
- `datagouv__deliberations-du-conseil-municipal-de-la-commune-de-lys-saint-georges-pour-la-periode-2018-2022` (decisions, ok, 0.1 Mo) : Délibérations du conseil municipal de la commune de Lys-Saint-Georges pour la période 2018 - 2022 
- `datagouv__deliberations-du-conseil-municipal-de-la-possession` (decisions, ok, 3.7 Mo) : Délibérations du conseil municipal de La Possession
- `datagouv__deliberations-du-conseil-municipal-de-la-ville-dantibes` (decisions, ok, 10.9 Mo) : Délibérations du Conseil municipal de la Ville d'Antibes
- `datagouv__deliberations-du-conseil-municipal-de-pontault-combault` (decisions, ok, 0.1 Mo) : Délibérations du Conseil municipal de Pontault-Combault
- `datagouv__deliberations-du-sieeen-1` (decisions, ok, 0.3 Mo) : Délibérations du SIEEEN
- `datagouv__deliberations-mairie-de-bouloc-1` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-mairie-de-bouloc-2` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-mairie-de-bouloc-3` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-mairie-de-bouloc-4` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-mairie-de-bouloc-5` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-mairie-de-bouloc-6` (decisions, ok, 0.0 Mo) : Délibérations (Mairie de Bouloc)
- `datagouv__deliberations-organisation-commune-de-taugon` (decisions, ok, 0.0 Mo) : Délibérations (organisation Commune de Taugon)
- `datagouv__deliberations-ville-de-boe` (decisions, ok, 1.0 Mo) : Délibérations - Ville de Boé
- `datagouv__departementales-les-depenses-retenues-et-les-voix-obtenues-des-candidats-par-canton` (politique, ok, 1.5 Mo) : Départementales. Les dépenses retenues et les voix obtenues des candidats par canton
- `datagouv__depenses-de-lexecutif-et-du-cabinet-du-conseil-regional-hauts-de-france-2016-2021` (collectivites, ok, 1.9 Mo) : Dépenses de l’exécutif et du Cabinet du Conseil régional Hauts-de-France (2016-2021)
- `datagouv__deputes-actifs` (politique, ok, 9.4 Mo) : Députés actifs
- `datagouv__dispositif-villages-davenir` (collectivites, ok, 0.1 Mo) : Dispositif Villages d'avenir
- `datagouv__donnees-du-hackathon-sur-les-donnees-essentielles-de-la-commande-publiques-reformatees-et-agregees` (beneficiaires, ok, 0.6 Mo) : Données du hackathon sur les données essentielles de la commande publiques reformatées et agrégées
- `datagouv__donnees-essentielles-des-conventions-de-subvention-de-la-region-bourgogne-franche-comte` (decisions, ok, 1.1 Mo) : Données essentielles des conventions de subvention de la Région Bourgogne-Franche-Comté
- `datagouv__duree-des-phases-dinstruction-arcep-licences-telecoms-en-france` (decisions, ok, 0.0 Mo) : Durée des phases d'instruction ARCEP licences telecoms en France
- `datagouv__elections-legislatives-generales-des-30-juin-et-7-juillet-2024` (politique, ok, 1.1 Mo) : Elections législatives générales des 30 juin et 7 juillet 2024
- `datagouv__elections-municipales-2014-candidats-dans-les-communes-de-moins-de-1-000-habitants` (politique, ok, 69.5 Mo) : Elections municipales 2014 - Candidats dans les communes de moins de 1 000 habitants 
- `datagouv__elections-municipales-2014-elus-au-1er-tour-communes-de-1-000-habitants-et-plus` (collectivites, ok, 18.0 Mo) : Elections municipales 2014 - Elus au 1er tour (communes de 1 000 habitants et plus)
- `datagouv__elections-municipales-2014-elus-au-1er-tour-communes-de-moins-de-1-000-habitants` (collectivites, ok, 35.5 Mo) : Elections municipales 2014 - Elus au 1er tour (communes de moins de 1 000 habitants)
- `datagouv__elections-municipales-2014-liste-des-elus-communes-de-1-000-habitants-et-plus` (collectivites, ok, 37.8 Mo) : Elections municipales 2014 – Liste des élus (communes de 1 000 habitants et plus) 
- `datagouv__elections-municipales-2014-liste-des-elus-communes-de-moins-de-1-000-habitants` (collectivites, ok, 54.0 Mo) : Elections municipales 2014 – Liste des élus (communes de moins de 1 000 habitants) 
- `datagouv__elections-municipales-2020-liste-des-candidats-elus-au-t1-et-liste-des-communes-entierement-pourvues` (politique, ok, 45.0 Mo) : Elections municipales 2020 - Liste des candidats élus au T1 et liste des communes entièrement pourvues
- `datagouv__elections-regionales-des-6-et-13-decembre-2015` (politique, ok, 0.0 Mo) : Elections régionales des 6 et 13 décembre 2015
- `datagouv__elections-senatoriales-des-27-septembre-2020-et-26-septembre-2021` (politique, ok, 0.2 Mo) : Elections sénatoriales des 27 septembre 2020 et 26 septembre 2021
- `datagouv__enquete-num-enquete-nationale-sur-les-usages-numeriques-des-collectivites-territoriales` (collectivites, ok, 0.3 Mo) : Enquête Num - Enquête nationale sur les usages numériques des collectivités territoriales
- `datagouv__evolution-des-recettes-de-la-taxe-de-sejour-de-2006-a-2014` (fiscalite, ok, 0.1 Mo) : Evolution des recettes de la taxe de séjour de 2006 à 2014
- `datagouv__fabriques-de-territoire-1` (beneficiaires, ok, 0.0 Mo) : Fabriques de territoire
- `datagouv__fichier-historique-des-deputes-et-de-leurs-mandats` (politique, ok, 21.7 Mo) : Fichier historique des Députés et de leurs mandats
- `datagouv__hautes-remunerations-fonction-publique-1-3` (collectivites, partiel, 0.0 Mo) : Martigues - Les dix plus hautes rémunérations dans la fonction publique - CCAS
- `datagouv__hautes-remunerations-fonction-publique-2-3` (collectivites, partiel, 0.0 Mo) : Martigues - Les dix plus hautes rémunérations dans la fonction publique - Commune
- `datagouv__hautes-remunerations-fonction-publique-3-3` (collectivites, partiel, 0.0 Mo) : Martigues - Les dix plus hautes rémunérations dans la fonction publique - CIAS
- `datagouv__jorf-les-donnees-de-l-edition-lois-et-decrets-du-journal-officiel` (etat, ok, 0.2 Mo) : JORF: les données de l'édition ''Lois et décrets'' du Journal officiel 
- `datagouv__la-conduite-des-grands-projets-numeriques-de-letat` (etat, ok, 0.0 Mo) : La conduite des grands projets numériques de l'État
- `datagouv__la-gestion-de-pole-emploi-dix-ans-apres-sa-creation` (beneficiaires, ok, 0.0 Mo) : La gestion de Pôle emploi, dix ans après sa création
- `datagouv__legislatives-2012-depenses-des-candidats` (politique, ok, 0.0 Mo) : Législatives 2012 - Dépenses des candidats
- `datagouv__les-perspectives-financieres-du-haut-conseil-du-commissariat-aux-comptes` (secu, ok, 0.0 Mo) : Les perspectives financières du Haut Conseil du commissariat aux comptes 
- `datagouv__linclusion-bancaire-et-la-prevention-du-surendettement-1` (etat, ok, 0.0 Mo) : L’inclusion bancaire et la prévention du surendettement
- `datagouv__liste-des-deliberations-des-conseils-municipaux` (decisions, ok, 0.7 Mo) : Liste des délibérations des conseils municipaux
- `datagouv__liste-des-deliberations-du-ccas-de-saint-ave-en-2019` (decisions, ok, 0.0 Mo) :  Liste des délibérations du CCAS de Saint-Avé en 2019
- `datagouv__marches-publics-2012-toulouse-metropole-tm` (beneficiaires, ok, 0.3 Mo) : Marchés publics 2012 Toulouse Métropole
- `datagouv__mesures-fiscales-des-candidats-a-lelection-presidentielle-2027` (politique, ok, 0.0 Mo) : Mesures fiscales des candidats à l'élection présidentielle 2027
- `datagouv__municipales-2014-depenses-des-candidats` (politique, ok, 0.0 Mo) : Municipales 2014 - Dépenses des candidats
- `datagouv__proces-verbal-et-compte-rendu-des-conseils-municipaux-2017` (divers, ok, 82.4 Mo) : Procès-verbal et compte-rendu des conseils municipaux 2017
- `datagouv__recueil-des-actes-administratifs-1` (decisions, ok, 83.2 Mo) : Recueil des Actes Administratifs
- `datagouv__recueil-des-actes-administratifs-raa-1` (decisions, ok, 434.0 Mo) : Recueil des Actes Administratifs (RAA)
- `datagouv__reglement-local-de-publicite-le-val` (decisions, ok, 9.0 Mo) : Règlement Local de Publicité - Le Val
- `datagouv__remuneration-du-dirigeant-de-sasu-ou-deurl-cotisations-net-et-impot-selon-le-montant` (fiscalite, ok, 0.0 Mo) : Rémunération du dirigeant de SASU ou d'EURL : cotisations, net et impôt selon le montant
- `datagouv__repertoire-des-representants-dinterets` (politique, lourd_ignore, 0.0 Mo) : Répertoire des représentants d'intérêts
- `datagouv__schema-directeur-des-infrastructures-de-recharge-de-vehicules-electriques-de-haute-vienne` (decisions, ok, 0.0 Mo) : Schéma directeur des infrastructures de récharge de véhicules électriques de Haute Vienne 
- `datagouv__subventions-de-bourges-plus-en-2018-et-2019` (beneficiaires, partiel, 1.6 Mo) : Subventions de Bourges Plus en 2018 et 2019
- `datagouv__tableau-general-des-elections-legislatives-des-10-et-17-juin-2012` (politique, ok, 0.8 Mo) : Tableau général des élections législatives des 10 et 17 juin 2012
- `decisions_d44_deliberations` (decisions, ok, 0.5 Mo) : Rapports, deliberations et proces-verbaux du Conseil departemental de Loire-Atlantique
- `decisions_megalis_deliberations` (decisions, ok, 212.8 Mo) : Deliberations des organismes adherents de Megalis Bretagne (un fichier par an)
- `decisions_nantes_metropole_deliberations` (decisions, ok, 0.4 Mo) : Deliberations des instances de Nantes Metropole
- `decisions_pdl_deliberations` (decisions, ok, 1.3 Mo) : Rapports, deliberations et proces-verbaux de la Region Pays de la Loire
- `economie__ambassadeursia` (divers, ok, 0.1 Mo) : Ambassadeurs IA - Osez l'IA
- `economie__dgccrf_annuaire_services_deconcentres` (collectivites, ok, 0.4 Mo) : DGCCRF - Annuaire des services déconcentrés
- `economie__ir-declarations-2042-nat` (fiscalite, ok, 0.4 Mo) : L'impôt sur le revenu : les déclarations nationales
- `economie__plan-de-relance-tableau-de-bord` (beneficiaires, ok, 0.8 Mo) : Plan de relance - Tableau de bord
- `economie__relance-tableau-de-bord` (beneficiaires, ok, 1.7 Mo) : Tableau de bord France Relance (format widget)
- `economie__tableau-de-bord-afa-format-widget` (divers, ok, 0.1 Mo) : Tableau de bord AFA (format widget)
- `economie__tableau-de-bord-impact-format-widget` (divers, ok, 0.0 Mo) : Tableau de bord Impact (format widget)
- `esr__fr-esr-laureats-concours-national-i-lab` (beneficiaires, ok, 2.2 Mo) : Lauréats I-LAB Concours national d'aide à la création d'entreprises de technologies innovantes
- `esr__fr-esr-porteur-jury-expert-aap-fonds-national-pour-la-science-ouverte` (divers, ok, 0.0 Mo) : Appels à projets Fonds national pour la science ouverte - Porteurs, jury et experts
- `europe_feder_fse_2021_2027_regions` (europe, ok, 1.6 Mo) : Beneficiaires FEDER/FSE+ 2021-2027 (Ile-de-France, Bretagne, Normandie)
- `europe_kohesio_2014_2020_fr` (europe, ok, 143.6 Mo) : Kohesio, projets de cohesion 2014-2020 en France
- `ods_ampmetropole__fr-centre-ville-fragilise` (europe, ok, 0.1 Mo) : Centres-villes fragilisés éligibles au dispositif ITI-FEDER (2021-2027)
- `ods_anglet_opendatapaysbasque__20220407-perimetre_conseils_quartier-21640024200014_anglet` (collectivites, ok, 0.0 Mo) : Périmètre des conseils de quartier sur la commune d'Anglet
- `ods_anglet_opendatapaysbasque__localisation-des-aires-de-jeux-pour-enfants-sur-la-commune-d-anglet` (collectivites, ok, 0.0 Mo) : Aires de jeux pour enfants sur la commune d'Anglet
- `ods_anglet_opendatapaysbasque__regie_anglet` (collectivites, ok, 0.0 Mo) : Régies d'avances et de recettes
- `ods_bretagne__sembreizh-od` (beneficiaires, ok, 0.7 Mo) : Marchés publics : données de la  SemBreizh
- `ods_cannes__plans-historiques` (fiscalite, ok, 0.0 Mo) : Plans historiques
- `ods_cc_coeurdefrance__base-sirene-v3-consolidee-des-etablissements-actifs-en-region-centre-val-de-loire` (collectivites, ok, 0.5 Mo) : Entreprises actives dans la Communauté de Communes Cœur de France
- `ods_cc_coeurdefrance__competences-epci` (collectivites, ok, 0.1 Mo) : Liste des EPCI et compétences / Arrondissement Saint-Amand-Montrond
- `ods_cc_coeurdefrance__cyclotourisme-veloroutes` (collectivites, ok, 1.8 Mo) : Cyclotourisme - Véloroutes en région Centre-Val de Loire
- `ods_cc_coeurdefrance__elus-conseillers-communautaires-municipaux` (collectivites, ok, 0.0 Mo) : Élus au conseil communautaire de la Communauté de Communes Cœur de France
- `ods_centrevaldeloire__associations-du-poinconnet-et-leur-subvention-en-2021` (beneficiaires, ok, 0.0 Mo) : Associations du Poinçonnet et leur subvention en 2021
- `ods_centrevaldeloire__associations-du-poinconnet-et-leur-subvention-en-2026` (beneficiaires, ok, 0.0 Mo) : Associations du Poinçonnet et leur subvention en 2026
- `ods_centrevaldeloire__donnees-du-repertoire-national-des-elus-locaux-rcvl` (collectivites, ok, 0.7 Mo) : Données du Répertoire national des élues locales et élus locaux  : Municipaux, Communautaires (EPCI) , Départementaux, Régionaux en région Centre-Val de Loire
- `ods_centrevaldeloire__organismes-de-formation-professionnelle-en-region-centre-val-de-loire` (collectivites, ok, 0.0 Mo) : [Archive] Organismes de formation professionnelle en Région Centre-Val de Loire (données détaillées) - 2024
- `ods_centrevaldeloire__organismes-de-formation-professionnelle-en-region-centre-val-de-loire-donnees-detaillees-2025` (collectivites, ok, 0.0 Mo) : Organismes de formation professionnelle en Région Centre-Val de Loire (données détaillées) - 2025
- `ods_clermontmetropole__bp20220` (etat, ok, 0.2 Mo) : Budget 2023 - Ville de Clermont-Ferrand
- `ods_doubs__communes` (collectivites, ok, 2.7 Mo) : Communes du Doubs
- `ods_doubs__intercomunalites` (collectivites, ok, 0.5 Mo) : Intercommunalités (EPCI)
- `ods_fleurysurorne__donnees-du-repertoire-national-des-elus-locaux-municipaux-communautaires-epci-de` (collectivites, ok, 0.0 Mo) : Données du Répertoire national des élus locaux  : Elus municipaux et communautaires de Fleury-sur-Orne
- `ods_grandparissud__elections-legislatives-2022-1er-tour-resultats-par-bureau-de-vote-pour-les-c0` (collectivites, ok, 0.1 Mo) : [Elections législatives 2022 - 1er tour]  Résultats par bureau de vote pour les communes de GPS
- `ods_grandparissud__elections-legislatives-2022-2nd-tour-resultats-par-bureau-de-vote-pour-les-commu` (collectivites, ok, 0.0 Mo) : [Elections législatives 2022 - 2nd tour]  Résultats par bureau de vote pour les communes de GPS
- `ods_grandparissud__elections-municipales-2026-liste-1er-tour-candidat-e-s-pour-les-communes-de-gps` (politique, ok, 0.1 Mo) : [Élections municipales 2026 - 1er tour] Liste des Candidat.e.s pour les communes de GPS
- `ods_grandparissud__elections-presidentielles-2022-1er-tour-resultats-par-bureau-de-vote-pour-les-co` (collectivites, ok, 0.1 Mo) : [Elections présidentielles 2022 - 1er tour]  Résultats par bureau de vote pour les communes de GPS
- `ods_grandparissud__elections-presidentielles-2022-2nd-tour-par-bureau-de-vote-pour-gps` (collectivites, ok, 0.0 Mo) : [Elections présidentielles 2022 - 2nd tour]  Résultats par bureau de vote pour les communes de GPS
- `ods_grandparissud__municipales-2026-1ertour-resultats-par-bv-des-communes-gps` (collectivites, ok, 0.1 Mo) : [Municipales 2026 - 1erTour] Résultats par BV des communes (GPS)
- `ods_grandparissud__municipales-2026-2ndtour-resultats-par-bv-des-communes-gps` (collectivites, ok, 0.1 Mo) : [Municipales 2026 - 2ndTour] Résultats par BV des communes (GPS)
- `ods_grandparissud__municipales-2026-resultats-par-bv-des-communes-gps` (collectivites, ok, 0.1 Mo) : [Municipales 2026] Résultats par BV des communes (GPS)
- `ods_ha_py__effectifs-salaries-du-secteur-prive-par-commune` (collectivites, lourd_ignore, 0.0 Mo) : Effectifs salariés du secteur privé, par commune dans les Hautes-Pyrénées de 2009 à 2024
- `ods_ha_py__etablissements-prives-employeurs-du-secteur-prive-par-commune` (collectivites, lourd_ignore, 0.0 Mo) : Etablissements privés employeurs du secteur privé, par commune dans les Hautes-Pyrénées de 2009 à 2024
- `ods_haute_garonne__repertoire-representants-interets-haute-garonne` (politique, ok, 0.0 Mo) : Répertoire des représentants d'intérêts en Haute-Garonne (source HATVP)
- `ods_hauts_de_seine__etablissements-habilites-au-titre-de-laide-sociale-a-lenfance-ase` (beneficiaires, ok, 0.0 Mo) : Etablissements habilités au titre de l'aide sociale à l'enfance (ASE)
- `ods_hauts_de_seine__fr-229200506-sites-daccueil-du-public-en-matiere-daction-sociale-et-medico-socia` (secu, ok, 0.0 Mo) : Sites d’accueil du public en matière d’action sociale et médico-sociale
- `ods_hauts_de_seine__partenaires-culturels` (collectivites, ok, 0.0 Mo) : Partenaires culturels
- `ods_herault_data__equipements-sportifs-communaute-de-communes-du-grand-pic-saint-loup` (collectivites, ok, 0.0 Mo) : Equipements sportifs - Communauté de communes du Grand Pic Saint Loup
- `ods_herault_data__relais-petite-enfance-communaute-de-communes-du-grand-pic-saint-loup` (collectivites, ok, 0.0 Mo) : Relais Petite Enfance - Communauté de Communes du Grand Pic Saint-Loup
- `ods_iledefrance__aide-regionale-equipement-pre-bac-2014-2015` (collectivites, ok, 0.0 Mo) : Dotation initiale à l’aide régionale à l’équipement pour les formations pré-bac en 2014-2015
- `ods_iledefrance__aide_a_l_equipement_des_formations_post-bac_2012-2013` (beneficiaires, ok, 0.0 Mo) : Aide à l'équipement des formations post-bac 2012-2013
- `ods_iledefrance__aide_a_l_equipement_des_lyceens_2012-2013` (beneficiaires, ok, 0.0 Mo) : Aide à l'équipement des lycéens 2012-2013
- `ods_iledefrance__aide_a_la_demi-pension_des_lyceens_2012-2013` (beneficiaires, ok, 0.0 Mo) : Aide à la demi-pension des lycéens 2012-2013
- `ods_iledefrance__aide_a_la_demi-pension_formations_post-bac_2012-2013` (beneficiaires, ok, 0.0 Mo) : Aide à la demi-pension des formations post-bac 2012-2013
- `ods_iledefrance__aide_regionale_aux_frais_de_concours_2012-2013` (beneficiaires, ok, 0.0 Mo) : Aide régionale aux frais de concours  (2012-2013)
- `ods_iledefrance__dotation-de-laide-regionale-aux-frais-de-concours-en-2013-2014` (collectivites, ok, 0.0 Mo) : Dotation de l’aide régionale aux frais de concours en 2013-2014
- `ods_iledefrance__dotation-de-laide-regionale-aux-frais-de-concours-en-2014-2015` (collectivites, ok, 0.0 Mo) : Dotation de l’aide régionale aux frais de concours en 2014-2015
- `ods_iledefrance__dotation-initiale-a-laide-regionale-a-lequipement-pour-les-formations-post-bac-0` (collectivites, ok, 0.0 Mo) : Dotation initiale à l’aide régionale à l’équipement pour les formations post-bac en 2014-2015
- `ods_iledefrance__dotation-initiale-a-laide-regionale-a-lequipement-pour-les-formations-post-bac-e` (collectivites, ok, 0.0 Mo) : Dotation initiale à l’aide régionale à l’équipement pour les formations post-bac en 2013-2014
- `ods_iledefrance__dotation-initiale-a-laide-regionale-a-lequipement-pour-les-formations-pre-bac-en` (collectivites, ok, 0.0 Mo) : Dotation initiale à l’aide régionale à l’équipement pour les formations pré-bac en 2013-2014
- `ods_iledefrance__dotation-initiale-de-laide-regionale-a-la-demi-pension-pour-les-formations-post-` (collectivites, ok, 0.0 Mo) : Dotation initiale de l’aide régionale à la demi-pension pour les formations post-bac en 2013-2014
- `ods_iledefrance__dotation-initiale-de-laide-regionale-a-la-demi-pension-pour-les-formations-pre-b` (collectivites, ok, 0.0 Mo) : Dotation initiale de l’aide régionale à la demi-pension pour les formations pré-bac en 2013-2014
- `ods_iledefrance__dotation-initiale-de-laide-regionale-a-la-gratuite-des-manuels-scolaires-pour-l0` (collectivites, ok, 0.0 Mo) : Dotation initiale de l’aide régionale à la gratuité des manuels scolaires pour les formations pré-bac en 2014-2015
- `ods_iledefrance__dotation-initiale-de-laide-regionale-a-la-gratuite-des-manuels-scolaires-pour-le` (collectivites, ok, 0.0 Mo) : Dotation initiale de l’aide régionale à la gratuité des manuels scolaires pour les formations pré-bac en 2013-2014
- `ods_iledefrance__epa_iledefrance_wgs84` (collectivites, ok, 0.1 Mo) : Établissements publics d'aménagement (EPA) Île-de- France
- `ods_iledefrance__gratuite_des_manuels_scolaires_2012-2013` (collectivites, ok, 0.0 Mo) : Gratuité des manuels scolaires 2012-2013
- `ods_iledefrance__indemnites-elus-regionaux-ile-de-france` (etat, ok, 0.0 Mo) : État présentant l'ensemble des indemnités des élus régionaux d’Île-de-France au sens de l'article L. 4135-19-2-1 du CGCT (montant brut mensuel)
- `ods_iledefrance__partenaires_culturels_des_hauts-de-seine` (collectivites, ok, 0.0 Mo) : Partenaires culturels des Hauts-de-Seine
- `ods_iledefrance__sites-inscrits-en-region-ile-de-france` (collectivites, ok, 1.0 Mo) : Sites inscrits en région Île-de-France
- `ods_iledefrance__subventions-versees-par-la-region-ile-de-france-aux-associations` (collectivites, ok, 0.6 Mo) : Subventions versées par la Région Île-de-France aux associations
- `ods_iledefrance__velo_amenag_projets_iledefrance_wgs84` (collectivites, ok, 0.4 Mo) : Projets d'aménagements cyclables subventionnés par la Région Île-de-France
- `ods_iledefrance__zone-daide-a-finalite-regionale-afr` (beneficiaires, ok, 1.1 Mo) : Zone d'Aide à Finalité Régionale (AFR)
- `ods_isere__epci-fiscalite-propre-isere` (fiscalite, ok, 1.3 Mo) : Établissements publics de coopération intercommunale à fiscalité propre de l'Isère
- `ods_issy__les-lieux-daide-a-lemploi-et-aux-entreprises-a-issy-les-moulineaux` (beneficiaires, ok, 0.0 Mo) : Les lieux d'aide à l'emploi et aux entreprises à Issy-les-Moulineaux
- `ods_issy__pastedtext` (fiscalite, ok, 0.0 Mo) : Liste des services publics à Issy-les-Moulineaux
- `ods_issy__principales-depenses-equipements-issy` (etat, ok, 0.0 Mo) : Principales dépenses d'équipement depuis 2008 à Issy-les-Moulineaux
- `ods_laregion__annuaire_maisons_region` (collectivites, ok, 0.0 Mo) : annuaire des maisons de Ma Région en Occitanie
- `ods_laregion__bp2026_apae` (collectivites, ok, 0.0 Mo) : Budget Primitif 2026 de la Région Occitanie (autorisations de programme/ autorisations d'engagement)
- `ods_laregion__bp2026_cp` (collectivites, ok, 0.0 Mo) : Budget Primitif 2026 de la Région Occitanie (crédits de paiement)
- `ods_laregion__budget-2026-supplementaire-ap-ae` (collectivites, ok, 0.0 Mo) : Budget supplémentaire 2026 de la Région Occitanie (autorisations de programme / autorisations d'engagement)
- `ods_laregion__budget-2026-supplementaire-de-la-region-occitanie-credits-de-paiement` (collectivites, ok, 0.0 Mo) : Budget supplémentaire 2026 de la Région Occitanie (crédits de paiement)
- `ods_laregion__subventions-du-conseil-regional` (beneficiaires, ok, 4.0 Mo) : Subventions du Conseil Régional
- `ods_loire_atlantique__224400028_aide-a-linstallation-des-agriculteurs-en-loire-atlantique` (beneficiaires, ok, 0.0 Mo) : Aide à l'installation des agriculteurs en Loire-Atlantique de 2008 à 2015
- `ods_loire_atlantique__224400028_clubs-sportifs-soutenus-pour-la-formation-en-loire-atlantique` (beneficiaires, ok, 0.0 Mo) : Clubs sportifs soutenus pour la formation  en Loire-Atlantique
- `ods_loire_atlantique__224400028_unites-aide-sociale-enfance-ase-loire-atlantique` (beneficiaires, ok, 0.0 Mo) : Unités d'Aide Sociale à l'Enfance (ASE) en Loire-Atlantique
- `ods_metropole_rouen_normandie__cadastre-communes-metropole-rouen-normandie-sage-cailly-aubette-robec` (collectivites, ok, 0.9 Mo) : Cadastre - Communes - Métropole Rouen Normandie / SAGE Cailly Aubette Robec
- `ods_meudon__sites-daccueil-du-public-en-matiere-daction-sociale-et-medico-sociale` (secu, ok, 0.0 Mo) : Sites d’accueil du public en matière d’action sociale et médico-sociale
- `ods_mulhouse_alsace__68224_localisation_caracteristiques_points-daide-alimentaire_mulhouse` (beneficiaires, ok, 0.0 Mo) : Points d'aide alimentaire sur Mulhouse
- `ods_nantesmetropole__244400404_communes-nantes-metropole` (collectivites, ok, 0.5 Mo) : Communes de Nantes Métropole
- `ods_opendata56__56011_budget_2017_begannev4` (etat, ok, 0.0 Mo) : BUDGET 2017
- `ods_opendata56__56232_budget-principal-2017` (etat, ok, 0.0 Mo) : Budget Principal 2017
- `ods_opendata56__composition-de-lassemblee-deliberante-de-morbihan-energies` (fiscalite, ok, 0.0 Mo) : Composition de l'assemblée délibérante de Morbihan énergies
- `ods_orleans_metropole__quartiers-participation-citoyenne-ville-orleans` (etat, ok, 0.1 Mo) : Participation citoyenne (quartiers et mairies de proximité) - Ville d'Orléans
- `ods_paris__nombre-dassociations-subventionnees-par-la-ville-de-paris-copie` (beneficiaires, ok, 0.5 Mo) : Nombre d’associations subventionnées par la Ville de Paris
- `ods_paris__subventions-associations-votees-` (beneficiaires, ok, 5.6 Mo) : Subventions aux associations votées
- `ods_paysdelaloire__234400034_005-001_fonds-documentaire-general-rpdl` (collectivites, ok, 0.6 Mo) : Fonds documentaire général de la Région des Pays de la Loire
- `ods_paysdelaloire__234400034_fluxinterventionsprod_pdl` (collectivites, ok, 0.5 Mo) : Interventions de la Région des Pays de la Loire
- `ods_paysdelaloire__close-data-liste-des-groupements-de-communes-en-pays-de-la-loire-banatic-par-com` (collectivites, ok, 11.1 Mo) : Liste des groupements de communes en Pays de la Loire [ BANATIC ]
- `ods_rennesmetropole__zonage_plh_rennes_metropole` (divers, ok, 1.2 Mo) : Zonage Robien et financement du Plan Local de l'Habitat de Rennes Métropole
- `ods_saint_louis_agglo__communes_elus` (collectivites, ok, 0.2 Mo) : SLA - Le territoire (Communes, Maire, Population)
- `ods_sarthe__227200029_solidarite-service-daide-a-domicile-par-commune` (collectivites, ok, 30.7 Mo) : Les services d'aide à domicile en Sarthe par commune
- `ods_seineouest__reglementation-et-arretes-sur-la-commune-de-marnes-la-coquette` (collectivites, ok, 0.0 Mo) : Règlementation et arrêtés sur la commune de Marnes-la-Coquette
- `ods_seinesaintdenis__appel-a-projet-seine-saint-denis` (collectivites, ok, 0.1 Mo) : Appel à projets - Seine-Saint-Denis
- `ods_strasbourg__boucles_sportives_vitaboucle` (dette, ok, 0.2 Mo) : Boucles sportives : Vitaboucle
- `ods_strasbourg__extrait_rne_ems` (collectivites, ok, 0.0 Mo) : Data from the National Registry of Elected Officials: Municipal, Intercommunal (EPCI), Departmental, and Regional
- `ods_strasbourg__ha_opah_ru_contour` (etat, ok, 0.0 Mo) : Opération Programmée d' Amélioration de l' Habitat de Renouvellement Urbain (OPAH RU)
- `ods_strasbourg__limites_de_communes` (collectivites, ok, 0.5 Mo) : Limites de communes
- `ods_strasbourg__marches_geo_contours` (beneficiaires, ok, 1.5 Mo) : Marchés - geo_contours
- `ods_strasbourg__ur_nat_presta_ecologique` (collectivites, ok, 0.1 Mo) : Expertise de prestations écologiques
- `ods_toulouse_metropole__open-datasubv2012` (beneficiaires, ok, 0.0 Mo) : Subventions versées à des tiers - 2012 - Ville de Toulouse
- `ods_toulouse_metropole__subventions-versees-2014-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2014 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2015-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2015 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2016-aeroscopia-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2016 - Aéroscopia Blagnac
- `ods_toulouse_metropole__subventions-versees-2016-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2016 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2017-aeroscopia-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2017 - Aéroscopia Blagnac
- `ods_toulouse_metropole__subventions-versees-2017-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2017 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2018-aeroscopia-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions Versées 2018 - Aéroscopia Blagnac
- `ods_toulouse_metropole__subventions-versees-2019-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2019 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2020-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2020 - Blagnac
- `ods_toulouse_metropole__subventions-versees-2021` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2021-Blagnac
- `ods_toulouse_metropole__subventions-versees-2022` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2022 Blagnac
- `ods_toulouse_metropole__subventions-versees-2023-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2023 Blagnac
- `ods_toulouse_metropole__subventions-versees-2024-blagnac` (beneficiaires, ok, 0.0 Mo) : Subventions versées 2024-Blagnac
- `ods_toulouse_metropole__subventions-versees-a-des-organismes-2015` (beneficiaires, ok, 0.0 Mo) : Subventions versées à des organismes 2015 - Ville de Toulouse
- `ods_toulouse_metropole__subventions-versees-a-des-organismes-2016-ville-de-toulouse` (beneficiaires, ok, 0.1 Mo) : Subventions versées à des organismes 2016 - Ville de Toulouse
- `ods_toulouse_metropole__subventions-versees-a-des-organismes-toulouse-metropole-2015` (beneficiaires, ok, 0.0 Mo) : Subventions versées à des organismes - Toulouse Métropole 2015
- `ods_toulouse_metropole__subventions-versees-a-des-tiers-2013-ville-de-toulouse` (beneficiaires, ok, 0.0 Mo) : Subventions versées à des tiers - 2013 - Ville de Toulouse
- `ods_toulouse_metropole__subventions-versees-a-des-tiers-2014-ville-de-toulouse` (beneficiaires, ok, 0.1 Mo) : Subventions versées à des tiers - 2014 - Ville de Toulouse
- `ods_toulouse_metropole__subventions-versees-a-des-tiers-2014-ville-de-toulouse0` (beneficiaires, ok, 0.0 Mo) : Subventions versées à des tiers - 2014 - Ville de Toulouse
- `ods_tours_metropole__aides-etudiants-tours-metropole-val-de-loire` (beneficiaires, ok, 0.0 Mo) : Aides pour les étudiants - COVID19 - Tours Métropole Val de Loire
- `ods_tours_metropole__sirene-v3-consolidee-rcvl` (collectivites, ok, 8.0 Mo) : Base SIRENE (v3 consolidée) des établissements actifs en Région Centre-Val de Loire
- `ofgl__actifs-gfp` (fiscalite, ok, 0.2 Mo) : Actif réévalué des groupements à fiscalité propre 2025
- `ofgl__actifs_communes` (collectivites, ok, 14.3 Mo) : Actif réévalué des communes 2025
- `ofgl__correspondance-code-siren-gfp-2023` (fiscalite, ok, 0.6 Mo) : Méthodologie OFGL - Historique des groupements à fiscalité propre - périmètre 2023
- `ofgl__correspondance-code-siren-gfp-2024` (fiscalite, ok, 0.7 Mo) : Méthodologie OFGL - Historique des groupements à fiscalité propre - périmètre 2024
- `ofgl__correspondance-code-siren-gfp-2025` (fiscalite, ok, 0.8 Mo) : Méthodologie OFGL - Historique des groupements à fiscalité propre - périmètre 2025
- `ofgl__detail_compositions_intercommunales_2012_2022` (collectivites, ok, 27.5 Mo) : detail_compositions_intercommunales_2012_2022
- `ofgl__detail_compositions_intercommunales_2012_2023` (collectivites, ok, 29.5 Mo) : detail_compositions_intercommunales_2012_2023
- `ofgl__detail_compositions_intercommunales_2012_2024` (collectivites, ok, 31.9 Mo) : detail_compositions_intercommunales_2012_2024
- `ofgl__detail_compositions_intercommunales_2012_2025` (collectivites, ok, 32.8 Mo) : detail_compositions_intercommunales_2012_2025
- `ofgl__disponibilite-des-comptes-des-communes` (collectivites, ok, 23.7 Mo) : Disponibilité des comptes des communes 2012-2025
- `ofgl__disponibilite-des-comptes-des-ensembles-intercommunaux` (fiscalite, ok, 0.4 Mo) : Disponibilité des comptes des ensembles intercommunaux 2012-2025
- `ofgl__disponibilite-des-comptes-des-groupements-a-fiscalite-propre` (fiscalite, ok, 0.2 Mo) : Disponibilité des comptes des groupements à fiscalité propre 2012-2025
- `ofgl__donnees_carto_departements` (collectivites, ok, 1.9 Mo) : [CARTOGRAPHIE] donnees_carto_departements
- `ofgl__donnees_carto_eis` (divers, ok, 11.7 Mo) : [CARTOGRAPHIE] donnees_carto_ei
- `ofgl__donnees_carto_gfps` (divers, ok, 22.9 Mo) : [CARTOGRAPHIE] donnees_carto_gfp
- `ofgl__donnees_carto_regions` (divers, ok, 0.3 Mo) : [CARTOGRAPHIE] donnees_carto_regions
- `ofgl__donnees_carto_sdis` (divers, ok, 0.8 Mo) : [CARTOGRAPHIE] donnees_carto_sdis
- `ofgl__populations-ofgl-departements` (collectivites, ok, 0.0 Mo) : Interne - Populations des départements 2012-2025
- `ofgl__populations-ofgl-ei` (fiscalite, ok, 0.8 Mo) : Interne - Population des ensembles intercommunaux 2012-2025
- `ofgl__populations-ofgl-gfp` (fiscalite, ok, 0.8 Mo) : Interne - Population des groupements à fiscalité propre 2012-2025
- `politique_campagne_legislatives_2022` (politique, ok, 1.8 Mo) : Comptes de campagne, legislatives 2022 (CNCCFP)
- `politique_campagne_legislatives_2024` (politique, ok, 1.1 Mo) : Comptes de campagne, legislatives 2024 (CNCCFP)
- `politique_campagne_municipales_2020` (politique, ok, 1.5 Mo) : Comptes de campagne, municipales 2020 (CNCCFP)
- `politique_hatvp_lobbying_csv` (politique, ok, 14.3 Mo) : Repertoire des representants d'interets (HATVP), vues separees CSV
- `politique_hatvp_lobbying_json` (politique, ok, 139.2 Mo) : Repertoire des representants d'interets (HATVP), JSON complet
- `recherche_anr_partenaires` (beneficiaires, ok, 18.8 Mo) : Partenaires des projets ANR
- `recherche_anr_projets` (beneficiaires, ok, 141.9 Mo) : Projets finances par l'ANR
- `urssaf__liste-des-directrices-et-des-directeurs` (secu, ok, 0.0 Mo) : Liste des directrices et des directeurs du réseau des Urssaf
- `urssaf__liste-des-presidents` (secu, ok, 0.0 Mo) : Liste des présidentes et des présidents du réseau des Urssaf

## Sources nommant des elus dans leur role public (7)

Votes et amendements nominatifs des parlementaires : zone publique, mais marques `elus_nommes`.

`decisions_an_l16_amendements`, `decisions_an_l16_scrutins`, `decisions_an_l17_amendements`, `decisions_an_l17_deputes`, `decisions_an_l17_scrutins`, `decisions_senat_ameli`, `decisions_senat_senateurs`

## Sources lourdes non prises

- `local_communes` (catalogue, lourde) : Comptes des communes (OFGL)
- `local_dotations_communes` (catalogue, lourde) : Dotations de l'Etat aux communes
- `local_balances_nature_fonction_2024` (catalogue, lourde) : Balances comptables nature x fonction 2024 (DGFiP)
- `decisions_an_l16_amendements` (catalogue, lourde) : Assemblee nationale, amendements de la 16e legislature
- `cdc__logements-sociaux-dans-les-communes` : ressource cdc__logements-sociaux-dans-les-communes.parquet (0 Mo, lourd (plus de 100 Mo))
- `cdc__moncompteformation_catalogueformation` : ressource cdc__moncompteformation_catalogueformation.parquet (0 Mo, lourd (plus de 100 Mo))
- `datagouv__comptes-rendus-du-senat` : ressource datagouv__comptes-rendus-du-senat/Comptes_rendus_int_graux_65875255.xml (0 Mo, lourd (plus de 100 Mo))
- `datagouv__donnees-essentielles-de-la-commande-publique-transmises-via-le-pes-marche` : ressource datagouv__donnees-essentielles-de-la-commande-publique-transmises-via-le-pes-marche/Donn_es_essentielles_du_PES_march_consolid_es_bf069d35.xml (0 Mo, lourd (plus de 100 Mo))
- `datagouv__dreal-occitanie-zonages-a-b-c-applicables-a-certaines-aides-au-logement` : ressource datagouv__dreal-occitanie-zonages-a-b-c-applicables-a-certaines-aides-au-logement/API_Geojson_99579ece.zip (0 Mo, lourd (plus de 100 Mo))
- `datagouv__repertoire-des-representants-dinterets` : ressource datagouv__repertoire-des-representants-dinterets/Fichier_complet_JSON_46cd8d72.json (0 Mo, lourd (plus de 100 Mo))
- `datagouv__subventions-cd76-2008-2023v1` : ressource datagouv__subventions-cd76-2008-2023v1/GeoJSON_aa858fda.geojson (0 Mo, lourd (plus de 100 Mo))
- `datagouv__subventions-cd76-2008-2023v1` : ressource datagouv__subventions-cd76-2008-2023v1/KML_7d5733a1.kml (0 Mo, lourd (plus de 100 Mo))
- `datagouv__webstat-cnf-1` : ressource datagouv__webstat-cnf-1/Ressource_CNF_016b3da1.csv (0 Mo, lourd (plus de 100 Mo))
- `economie__base-documentaire-des-notes-communicables-de-la-dgfip` : ressource economie__base-documentaire-des-notes-communicables-de-la-dgfip/2018_2022_NAUSICAA_export_OPENDATA.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_janvier_2025_-_dept_2A0_dept_580.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_janvier_2025_-_dept_590_dept_976.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_avril_2025_-dept_590_dept_976.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_avril_2025_-dept_2A0_dept_580.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_juillet_2025_-dept_2A0_dept_580.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_juillet_2025_-dept_590_dept_976.7z (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_Octobre_2025_-dept2A0_dept_500.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__documents-de-filiation-informatises-dfi-des-parcelles` : ressource economie__documents-de-filiation-informatises-dfi-des-parcelles/Documents_de_filiation_informatis_s_situation_Octobre_2025_-dept_510_dept_976.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichier-fantoir-des-voies-et-lieux-dits` : ressource economie__fichier-fantoir-des-voies-et-lieux-dits/Fichier_national_FANTOIR_situation_juillet_2022.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichier-fantoir-des-voies-et-lieux-dits` : ressource economie__fichier-fantoir-des-voies-et-lieux-dits/Fichier_national_FANTOIR_situation_novembre_2022.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichier-fantoir-des-voies-et-lieux-dits` : ressource economie__fichier-fantoir-des-voies-et-lieux-dits/Fichier_national_FANTOIR_situation_janvier_2023.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichier-fantoir-des-voies-et-lieux-dits` : ressource economie__fichier-fantoir-des-voies-et-lieux-dits/Fichier_national_FANTOIR_situation_avril_2023.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_locaux_situation_2019.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_parcelles_situation_2019_-dept_01_61.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_parcelles_situation_2019_-dept_62_976.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_locaux_situation_2020.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_parcelles_situation_2020_-dept_01_61.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_parcelles_situation_2020_-dept_62_976.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_locaux_situation_2021.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales` : ressource economie__fichiers-des-locaux-et-des-parcelles-des-personnes-morales/Fichier_des_parcelles_situation_2021_-dept_01_61.zip (0 Mo, lourd (plus de 100 Mo))
- `economie__fiscalite-locale-des-entreprises-copie` : ressource economie__fiscalite-locale-des-entreprises-copie.parquet (0 Mo, lourd (plus de 100 Mo))
- `economie__fiscalite-locale-des-particuliers-geo` : ressource economie__fiscalite-locale-des-particuliers-geo.parquet (0 Mo, lourd (plus de 100 Mo))
- `economie__offre-de-referentiels-pour-la-gestion-de-la-chaine-ressources-humaines-rh-de-letat-gestion-administrative-paye` : ressource economie__offre-de-referentiels-pour-la-gestion-de-la-chaine-ressources-humaines-rh-de-letat-gestion-administrative-paye/16-Fiches_de_maintenance_25.10.00.zip (0 Mo, lourd (plus de 100 Mo))
- `esr__fr-esr-h2020-projects-entities` : ressource esr__fr-esr-h2020-projects-entities.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_bordeaux_metropole__se_epci_s` : ressource ods_bordeaux_metropole__se_epci_s.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_ha_py__effectifs-salaries-du-secteur-prive-par-commune` : ressource ods_ha_py__effectifs-salaries-du-secteur-prive-par-commune.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_ha_py__etablissements-prives-employeurs-du-secteur-prive-par-commune` : ressource ods_ha_py__etablissements-prives-employeurs-du-secteur-prive-par-commune.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_iledefrance__actes-administratifs` : ressource ods_iledefrance__actes-administratifs.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_iledefrance__rapports-et-deliberations-du-conseil-regional-ile-de-france-et-de-sa-commission-` : ressource ods_iledefrance__rapports-et-deliberations-du-conseil-regional-ile-de-france-et-de-sa-commission-.parquet (0 Mo, lourd (plus de 100 Mo))
- `ods_laregion__fonds-de-solidarite-occitanie` : ressource ods_laregion__fonds-de-solidarite-occitanie.parquet (0 Mo, lourd (plus de 100 Mo))

### Jeux decouverts lourds non pris (125, environ 126 Go estimes)

Estimation grossiere (lignes x champs). Les exports ODS de plus de 300 Mo sont souvent coupes par le reseau ou trop lents (environ 0,3 Mo/s) : statut delai_depasse ou parquet incomplet.

- `datagouv__donnees-essentielles-de-la-commande-publique-fichiers-consolides` (8,654 Mo estimes, non tente) : Données essentielles de la commande publique - fichiers consolidés
- `ofgl__ofgl-base-communes` (7,344 Mo estimes, non tente) : Comptes des communes 2018-2025
- `economie__fichier-des-competences-territoriales-des-services-dgfip` (6,508 Mo estimes, non tente) : Fichier des compétences territoriales des services DGFIP
- `datagouv__resultats-du-controle-sanitaire-de-leau-distribuee-commune-par-commune` (6,072 Mo estimes, non tente) : Résultats du contrôle sanitaire de l'eau distribuée commune par commune
- `ofgl__ofgl-base-communes-consolidee` (4,440 Mo estimes, non tente) : Comptes consolidés des communes 2018-2025
- `ofgl__dotations-communes` (3,688 Mo estimes, non tente) : Dotations des communes - montants et critères
- `ofgl__rei` (3,644 Mo estimes, non tente) : (REI) Fiscalité directe locale 2024 - 2025
- `datagouv__rapports-dobservations-definitives-des-chambres-regionales-des-comptes-crc-et-reponses-associees-1` (3,573 Mo estimes, non tente) : Rapports d'observations définitives des Chambres Régionales des Comptes (CRC) et réponses associées
- `ods_bretagne__sirene-v3-consolidee` (2,805 Mo estimes, non tente) : Base SIRENE - Région Bretagne
- `datagouv__donnees-essentielles-de-la-commande-publique-transmises-via-le-pes-marche-depuis-2024` (2,229 Mo estimes, non tente) : Données essentielles de la commande publique transmises via le PES Marché depuis 2024
- `esr__fr-esr-sise-effectifs-d-etudiants-inscrits-esr-public` (2,004 Mo estimes, non tente) : Effectifs d'étudiants inscrits dans les établissements publics sous tutelle du ministère en charge d
- `datagouv__budgets-des-organismes-adherents-de-megalis-bretagne` (1,923 Mo estimes, non tente) : Budgets des organismes adhérents de Mégalis Bretagne
- `economie__balances-comptables-des-etablissements-publics-locaux-depuis-2010` (1,876 Mo estimes, non tente) : Balances comptables des établissements publics locaux depuis 2010
- `economie__balances-comptables-des-communes-en-2017` (1,645 Mo estimes, non tente) : Balances comptables des communes en 2017
- `economie__balances-comptables-des-communes-en-2019` (1,621 Mo estimes, non tente) : Balances comptables des communes en 2019
- `economie__balances-comptables-des-communes-en-2018` (1,619 Mo estimes, non tente) : Balances comptables des communes en 2018
- `economie__balances-comptables-des-communes-en-2022` (1,603 Mo estimes, non tente) : Balances comptables des communes en 2022
- `economie__balances-comptables-des-communes-en-2021` (1,591 Mo estimes, non tente) : Balances comptables des communes en 2021
- `economie__balances-comptables-des-communes-en-2020` (1,584 Mo estimes, non tente) : Balances comptables des communes en 2020
- `economie__balances-comptables-des-communes-en-2023` (1,581 Mo estimes, non tente) : Balances comptables des communes en 2023
- `economie__balances-comptables-des-communes-en-2024` (1,576 Mo estimes, non tente) : Balances comptables des communes en 2024
- `economie__balances-comptables-des-communes-en-2025` (1,560 Mo estimes, non tente) : Balances comptables des communes en 2025
- `economie__balances-comptables-des-communes-en-2016` (1,544 Mo estimes, non tente) : Balances comptables des communes en 2016
- `economie__balances-comptables-des-groupements-a-fiscalite-propre-depuis-2010` (1,436 Mo estimes, delai_depasse) : Balances comptables des groupements à fiscalité propre depuis 2010
- `economie__balances-comptables-des-communes-en-2015` (1,426 Mo estimes, non tente) : Balances comptables des communes en 2015
- ... et 100 autres

## Jeux decouverts exclus comme hors sujet (22)

Filtre par mots-cles (`EXCLUSIONS` dans collecte.py : PAC, patrimoine, vaccination, transports, etat civil, resultats electoraux...) et score minimal de pertinence.

- `datagouv__aides-percues-par-les-personnes-morales-au-titre-de-la-politique-agricole-commune` : Aides perçues par les personnes morales au titre de la Politique Agricole Commune
- `datagouv__aides-de-la-politique-agricole-commune-pac-30379066` : Aides de la politique agricole commune (PAC)
- `datagouv__aides-percues-au-titre-de-la-politique-agricole-commune-pac` : Aides perçues au titre de la Politique Agricole Commune (PAC
- `datagouv__cours-deau-retenus-au-titre-des-bcae-conditionnalite-des-aides-pac-dans-le-departement-du-var` : Cours d'eau retenus au titre des BCAE (conditionnalité des aides PAC) dans le département du Var
- `datagouv__montant-des-aides-percues-au-titre-de-la-pac` : Montant des aides perçues au titre de la PAC
- `datagouv__agriculture-en-france-aides-pac-pour-la-campagne-2022-ja-bio-et-dpb-8000eur` : Agriculture en France - Aides PAC pour la campagne 2022 (JA, Bio, et DPB > 8000€)
- `datagouv__aides-percus-par-les-beneficiaires-au-titre-de-la-pac` :  Aides perçus par les bénéficiaires au titre de la PAC
- `datagouv__aides-percus-par-les-beneficiaires-au-titre-de-la-pac-1` : Aides perçus par les bénéficiaires au titre de la PAC
- `datagouv__donnees-vaccination-par-pathologie-et-departement-region` : Données vaccination par pathologie et département / région
- `datagouv__donnees-de-vaccination-par-indice-de-defavorisation-et-tranche-dage` : Données de vaccination par indice de défavorisation et tranche d'âge
- `datagouv__donnees-vaccination-par-categorie-dinjecteur-hors-centres-de-vaccination-et-etablissements-de-sante` : Données vaccination par catégorie d'injecteur, hors centres de vaccination et établissements de sant
- `datagouv__donnees-vaccination-par-commune-lyon-marseille-paris` : Données vaccination par commune (Lyon, Marseille, Paris)
- `datagouv__donnees-vaccination-par-tranche-dage-type-de-vaccin-et-departement-region` : Données vaccination par tranche d'âge, type de vaccin et département / région
- `economie__resultats-des-elections-professionnelles-pour-les-comites-techniques-dans-la-fp-` : Résultats des élections professionnelles pour les comités techniques dans la fonction publique en 20
- `ods_angers__stat_etat_civil_angers` : Statistiques état civil - Angers
- `ods_boulognebillancourt_seineouest__resultats-des-elections-par-commune` : Résultats des élections par commune
- `ods_ha_py__departementdeshautespyrenees_numerisation_des_registres_d_etat_civil_empruntes_d` : Communes dont les registres d’état civil de 1893 à 1923 prêtés par les communes sont en ligne sur le
- `ods_haute_garonne__episode-de-pollution-departement-haute-garonne` : Episode de pollution département de la Haute-Garonne - Qualité de l'air
- `ods_herault_data__resultat-des-elections-presidentielles-de-la-commune-de-marseillan` : Résultat des élections présidentielles de la commune de Marseillan
- `ods_issy__les-statistiques-des-actes-de-letat-civil` : Actes d'état civil effectués en ligne
- `ods_opendata56__25560110600024_fichier-des-prenoms-edition-2016-pour-le-departement-du-morbihan` : Fichier des prénoms - Edition 2016 pour le département du Morbihan
- `ods_opendata56__fichier-des-prenoms-edition-2016-pour-le-departement-du-morbihan-copie` : Fichier des prénoms - Edition 2016 pour le département du Morbihan – copie

## Sources identifiees mais non collectables automatiquement

- Aides d'Etat (TAM, Commission europeenne) : session et jeton CSRF, export envoye par courriel
- Aides PAC beneficiaires : application sans URL stable ; publication legale limitee a 2 ans : exclu
- Agence France Tresor (dette negociable) : refus d'acces (Cloudflare 403), non contourne
- Contribution francaise au budget UE (xlsx) : HTTP 429 persistant
- Credit d'impot recherche, montants : publie en PDF seulement
- Voies et moyens tome 2, PLF 2024 a 2026 : publie en PDF seulement
- Bpifrance, CNC, DRAC, ANS (aides nominatives) : pas de jeu ouvert existant
- Declarations de patrimoine des elus (HATVP) : hors objet, donnees personnelles sensibles : exclu volontairement
- Banque de France Webstat (ODS, sans cle) : 43 000 series publiees chacune comme un jeu sans enregistrements ODS : non parcouru par la decouverte, a traiter par une selection de series
- data.ccomptes.fr, data.anct.gouv.fr : portails inexistants (nom de domaine non resolu) ; Cour des comptes et ANCT couvertes via leurs organisations data.gouv.fr
- Exports ODS de plus de 300 Mo (balances comptables par annee, comptes des communes OFGL) : transferts coupes ou trop lents via le reseau de collecte (environ 0,3 Mo/s) : a reprendre depuis une machine sans proxy
- BOAMP brut (DILA, echanges.dila.gouv.fr/OPENDATA/BOAMP) : un fichier XML par avis, des dizaines de milliers par mois : non pris en l'etat ; les marches attribues sont couverts par les DECP
- Cour des comptes, mouvements de credits 2015-2020 : les URL CSV redirigent vers une page web (302)
- HATVP liste.csv (index des declarations) : index des declarations de patrimoine et d'interets des responsables publics : exclu par la regle sur le patrimoine
- Legifrance, budget.gouv.fr (performance-publique), data.ccomptes.fr : refusent les scripts ou inexistants : non insiste

## Decouvertes automatiques

`collecte/decouvertes.json` genere le 2026-11-16T11:54:55+00:00 : 20093 jeux, dont 2099 doublons data.gouv.fr de portails ODS.

| Portail | Jeux | Score >= 4 | Collectes |
|---|---:|---:|---:|
| ameli | 51 | 3 | 9 |
| atih | 53 | 2 | 0 |
| caf | 210 | 3 | 73 |
| cdc | 89 | 20 | 63 |
| datagouv | 5939 | 3312 | 2400 |
| drees | 264 | 17 | 41 |
| economie | 619 | 447 | 524 |
| esr | 217 | 11 | 29 |
| ods_afd | 23 | 4 | 5 |
| ods_agglo_carene | 132 | 14 | 39 |
| ods_agglo_montargoise | 22 | 3 | 15 |
| ods_ampmetropole | 198 | 9 | 14 |
| ods_angers | 151 | 8 | 41 |
| ods_anglet_opendatapaysbasque | 145 | 2 | 10 |
| ods_aude | 29 | 1 | 2 |
| ods_bordeaux_metropole | 565 | 86 | 135 |
| ods_boulognebillancourt_seineouest | 83 | 2 | 3 |
| ods_bretagne | 189 | 14 | 25 |
| ods_cannes | 154 | 29 | 41 |
| ods_capatlantique | 160 | 24 | 63 |
| ods_cc_autourdechenonceaux | 19 | 0 | 1 |
| ods_cc_coeurdefrance | 81 | 4 | 11 |
| ods_centrevaldeloire | 382 | 66 | 132 |
| ods_chateauroux_metropole | 113 | 0 | 19 |
| ods_chaville_seineouest | 72 | 0 | 0 |
| ods_clermontmetropole | 126 | 13 | 16 |
| ods_dares_travail_emploi | 33 | 0 | 0 |
| ods_doubs | 50 | 6 | 15 |
| ods_education | 314 | 3 | 8 |
| ods_eurelien | 53 | 2 | 4 |
| ods_evrycourcouronnes | 40 | 0 | 8 |
| ods_fleurysurorne | 123 | 13 | 17 |
| ods_gers | 82 | 4 | 5 |
| ods_gpseo | 30 | 0 | 3 |
| ods_grandparissud | 427 | 17 | 42 |
| ods_ha_py | 195 | 16 | 31 |
| ods_haute_garonne | 287 | 29 | 52 |
| ods_hauts_de_seine | 254 | 12 | 29 |
| ods_herault_data | 328 | 38 | 48 |
| ods_iledefrance | 1039 | 117 | 194 |
| ods_iledefrance_mobilites | 94 | 1 | 3 |
| ods_isere | 110 | 8 | 16 |
| ods_issy | 327 | 32 | 41 |
| ods_lamayenne | 106 | 1 | 6 |
| ods_laregion | 205 | 16 | 25 |
| ods_loire_atlantique | 342 | 91 | 148 |
| ods_maine_et_loire | 128 | 23 | 40 |
| ods_metropole_rouen_normandie | 114 | 4 | 7 |
| ods_meudon | 113 | 1 | 7 |
| ods_mulhouse_alsace | 146 | 10 | 13 |
| ods_nantesmetropole | 592 | 164 | 199 |
| ods_normandie_education | 58 | 3 | 4 |
| ods_opendata56 | 89 | 12 | 16 |
| ods_orleans_metropole | 216 | 3 | 6 |
| ods_paris | 484 | 42 | 70 |
| ods_paysdelaloire | 213 | 25 | 39 |
| ods_rennesmetropole | 673 | 101 | 144 |
| ods_saint_louis_agglo | 67 | 15 | 27 |
| ods_saintnazaireagglo | 132 | 14 | 39 |
| ods_sarthe | 80 | 2 | 7 |
| ods_seineouest | 195 | 14 | 23 |
| ods_seinesaintdenis | 74 | 2 | 9 |
| ods_sevres_seineouest | 73 | 0 | 2 |
| ods_sicoval | 49 | 2 | 5 |
| ods_strasbourg | 401 | 5 | 27 |
| ods_te44 | 5 | 0 | 1 |
| ods_teo_paysdelaloire | 134 | 2 | 6 |
| ods_toulouse_metropole | 844 | 221 | 232 |
| ods_tours_metropole | 234 | 10 | 23 |
| ods_unedic | 50 | 2 | 10 |
| ods_vanves_seineouest | 58 | 0 | 1 |
| ods_vendee | 52 | 4 | 4 |
| ods_villedavray | 72 | 1 | 1 |
| ofgl | 96 | 46 | 77 |
| urssaf | 126 | 16 | 117 |
