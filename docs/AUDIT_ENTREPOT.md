# Audit de l'entrepôt brut : peut-on régénérer chaque axe ? (19/11/2026)

Question : pour chaque étape de `pipeline/tout.py`, où sont les fichiers bruts qu'elle lit (`pipeline/entrees_lac.json`), et lesquelles ne peuvent pas être régénérées aujourd'hui ? Tableau complet régénérable par `python pipeline/entrepot_distant.py diagnostic --markdown`.

## 1. État réel constaté (vérifications en lecture seule)

| Emplacement prévu | Constat du 19/11/2026 | Comment |
|---|---|---|
| VPS OVH `vps-367b6723` | **Collecte non déployée** : pas de minuterie `ovmi-collecte.timer` (inconnue de systemd), pas de `/etc/ovmi`, pas de `/var/lib/ovmi`, pas d'utilisateur `ovmi`, pas de `rclone`. Le VPS existe et sert à Hermes. | API OVH (`GET /vps`) puis SSH en lecture seule (`systemctl list-timers`, `ls -ld`, `command -v`, `id`) |
| Bucket public `ovmi-lake-public` | **Absent** : `NoSuchBucket` en GRA, 404 en RBX et SBG | requête HTTPS anonyme sur le point d'accès S3 |
| Bucket privé `ovmi-lake-prive` | **Absent** (404 en GRA, RBX, SBG) | idem |
| Projet Public Cloud, utilisateur S3 | non vérifiable : les outils OVH de la session ne listent pas les projets Public Cloud | à confirmer par Benjamin (docs/DEPLOIEMENT.md, partie 5) |
| Cache GitHub `lac-v1-*` | **vide en pratique** : le `data.yml` actuel (deux jobs, cache de l'entrepôt) date du 17/11 23:26 et n'a jamais tourné ; le dernier passage planifié (16/11) était l'ancienne version sans cache de l'entrepôt. L'API des caches est refusée par le proxy de la session. | `gh run list -w data.yml`, `git log -- .github/workflows/data.yml` |
| Variables et secrets du dépôt | non lisibles depuis la session | |
| Entrepôt local des agents (`/home/claude/ou-vont-mes-impots/data/lake`) | 4,5 Go, partiel, purgé régulièrement ; ce n'est pas une source durable | `du`, diagnostic |

Conséquence : aujourd'hui **aucune copie durable** des entrées n'existe. Chaque passage de `data.yml` repart des seules sources amont ; une source qui a changé (dump Ameli plus récent), qui a disparu ou qui refuse le robot donne une étape « conservée » et la version publiée ne peut plus être reproduite.

## 2. Par étape : entrées et possibilité de régénération

Colonnes : nombre d'entrées déclarées ; présentes sur le poste des agents ; en zone `_restreint` (personnes physiques, jamais en CI) ; absentes du poste ; moyen de recollecte. Aucune entrée n'est dans un bucket ni dans un cache GitHub (section 1).

| Étape | Entrées | Présentes (poste agents) | Zone restreinte | Absentes | Recollecte possible par |
|---|---:|---:|---:|---:|---|
| base | 0 | 0 | 0 | 0 | non relevé (lit data/raw, versionné, et le réseau) |
| beneficiaires | 8 | 6 | 1 | 2 | VPS seulement (restreint) ; collecter du module ; tout.py entrepot |
| operateurs | 5 | 3 | 0 | 2 | collecter du module ; tout.py entrepot |
| vie_politique | 10 | 6 | 1 | 4 | VPS seulement (restreint) ; collecter ; tout.py entrepot |
| realisations | 26 | 10 | 0 | 16 | collecter ; tout.py entrepot |
| decisions | 12 | 8 | 0 | 4 | collecter (JORF) ; tout.py entrepot |
| prelevements | 7 | 6 | 0 | 1 | collecter ; tout.py entrepot |
| secu | 3 | 2 | 0 | 1 | collecter ; tout.py entrepot |
| niches | 5 | 5 | 0 | 0 | collecter (PDF Assemblée nationale) ; tout.py entrepot |
| ue | 4 | 2 | 1 | 2 | VPS seulement (restreint) ; collecter ; tout.py entrepot |
| dette | 4 | 1 | 0 | 3 | collecter ; tout.py entrepot |
| tracabilite | 2 | 1 | 0 | 1 | collecter de realisations (amont) |
| local | 319 | 128 | 13 | 191 | VPS seulement (restreint) ; production en réseau ; tout.py entrepot |
| controle | 9 | 9 | 2 | 0 | VPS seulement (restreint) ; collecter ; tout.py entrepot |
| local_satellites | 27 | 27 | 0 | 0 | collecter ; tout.py entrepot |
| outremer | 24 | 24 | 0 | 0 | tout.py entrepot |
| recouvrement | 13 | 13 | 0 | 0 | tout.py entrepot |
| retraites | 11 | 11 | 0 | 0 | collecter du module (hors catalogue, relevé ajouté le 19/11) |
| sante_etablissements | 19 | 19 | 0 | 0 | collecter ; tout.py entrepot |
| solidarites_departements | 6 | 6 | 0 | 0 | tout.py entrepot |
| fonds_europeens | 32 | 32 | 6 | 0 | VPS seulement (restreint) ; collecter ; tout.py entrepot |
| aides_entreprises | 15 | 15 | 0 | 0 | collecter ; tout.py entrepot |
| logement | 10 | 10 | 0 | 0 | collecter ; tout.py entrepot |
| millesimes | 2 | 2 | 0 | 0 | collecte/collecte.py (sources etat_plrg_2024 et 2025) |
| revenus_communes | 26 | 26 | 0 | 0 | tout.py entrepot |
| series | 1 | 0 | 0 | 1 | collecter |
| agriculture | 4 | 0 | 0 | 4 | tout.py entrepot |
| transports | 7 | 1 | 0 | 6 | tout.py entrepot |
| energie_climat | 6 | 0 | 0 | 6 | tout.py entrepot |
| culture_medias | 22 | 1 | 0 | 21 | collecter ; tout.py entrepot |
| sport | 4 | 0 | 3 | 4 | VPS seulement (restreint) ; tout.py entrepot |
| petite_enfance | 14 | 1 | 0 | 13 | tout.py entrepot |
| eau_environnement | 8 | 6 | 6 | 2 | VPS seulement (restreint) ; tout.py entrepot |
| securite_interieure | 22 | 0 | 0 | 22 | tout.py entrepot |
| douanes_accises | 11 | 11 | 0 | 0 | tout.py entrepot |
| pouvoirs_publics | 8 | 8 | 0 | 0 | collecte/collecte.py ; tout.py entrepot |
| assurance_maladie_territoires | 5 | 5 | 0 | 0 | tout.py entrepot |
| fiscalite_locale_series | 1 | 1 | 0 | 0 | collecter |
| immobilier_etat | 16 | 16 | 0 | 0 | tout.py entrepot |
| performance | 113 | 113 | 0 | 0 | tout.py entrepot |
| typologies | 4 | 4 | 0 | 0 | tout.py entrepot |
| entites | 2 | 2 | 0 | 0 | caches de local (amont) |
| application_lois | 3 | 3 | 0 | 0 | collecter ; tout.py entrepot |
| deliberations | 4 | 4 | 1 | 0 | VPS seulement (restreint) ; collecter |
| investissement_communes | 2 | 2 | 0 | 0 | collecter |
| qui_a_vote | 6 | 4 | 0 | 2 | collecter ; tout.py entrepot |
| projets_subventionnes | 9 | 9 | 5 | 0 | VPS seulement (restreint) ; collecter ; tout.py entrepot |
| ma_commune | 1 | 0 | 0 | 1 | tout.py entrepot |
| fraicheur | 3 | 3 | 0 | 0 | collecter |
| local_fonctions, subventions, territoires, prestations, europe_comparaison, aide_developpement, associations, education_recherche, etat_actionnaire, fonction_publique, formation, justice_defense, marches, numerique_etat, emploi, datapackage | 0 | | | | non relevé : entrées inconnues (`tout.py inventorier` à rejouer sous strace avec un entrepôt complet) |

Totaux : 65 étapes ; 17 sans entrée relevée ; 10 avec au moins une entrée en zone restreinte (régénérables en entier sur le VPS seulement) ; 22 dont une entrée manque même sur le poste des agents. Entrées publiques présentes sur le poste : 1 000 fichiers, 3,0 Go (les plus gros : `_cache/local` 753 Mo, `revenus_communes_ircom` 370 Mo, amendements AN 364 Mo, dump Ameli 156 Mo).

### Axes signalés

- **decisions** : le cache `data/lake/_cache/decisions_jorf` (incréments JORF) est absent et `data/lake/etat/realisations` aussi ; le dump Ameli du Sénat présent (17/11) est plus récent que celui de la version publiée, dont l'empreinte n'a été enregistrée nulle part. Régénérable par recollecte (version nouvelle), **pas reproductible** à l'identique.
- **retraites** : les 11 entrées sont présentes ; elles n'étaient pas déclarées dans `entrees_lac.json` (collectées par le module, hors catalogue) : relevé ajouté. Le test de reproductibilité échouait parce que la date écrite (`date_sources("secu")`) suivait la collecte la plus récente du domaine `secu` sur le poste (18/11, une autre source), pas la version publiée (17/11). **Reproduit à l'identique** avec la lignée enregistrée.
- **niches** : le dossier `fiscalite/niches_vm` (PDF tome II) avait été purgé ; `python pipeline/niches.py collecter` l'a rapatrié depuis l'Assemblée nationale (accessible le 19/11) et la sortie publiée est **reproduite à l'identique** (date du 16/11). Le test `tests/test_reproductibilite.py` échouait car il ne vérifiait que les sources du catalogue, pas ce dossier hors catalogue.
- **millesimes** : entrées présentes ; la sortie ne diffère de la version publiée que par `bascule`, inventaire du code du dépôt (modules et écrans qui lisent l'exécution 2024), qui change à chaque nouveau module sans que la source change. **Reproduit** hors `bascule`.
- **local** : 191 entrées sur 319 absentes du poste, 13 en zone restreinte : régénérable seulement par une longue recollecte (production en réseau reprenable par passages de 480 s), et en entier sur le VPS seulement.
- **lignée du datapackage** : `docs/datapackage/sources.csv` ne reprend que les sources du catalogue (`sources` de `entrees_lac.json`) : ni les entrées hors catalogue, ni les caches, ni la version (empreinte, date) des fichiers lus. La lignée des versions est désormais dans `pipeline/lignee.json` (3 étapes vérifiées) ; la relier au datapackage est une suite à donner par le responsable de `pipeline/datapackage.py`.

## 3. Cause de fond

1. L'architecture de `docs/STOCKAGE.md` range chaque source **convertie en Parquet** sans garder l'original. Les modules lisent les octets d'origine (CSV, XLSX, PDF, ZIP) et leurs sorties en dépendent : même déployé, ce bucket ne suffit pas à rejouer le pipeline.
2. Aucune empreinte des entrées utilisées pour une sortie publiée n'était enregistrée : impossible de savoir si l'entrepôt local est « le bon ».
3. Les tests de reproductibilité comparaient à « ce qui traîne en local » : dates tirées du domaine entier, contrôle de présence limité aux sources du catalogue.
4. Rien n'empêchait une publication où un axe perd des lignes (source partielle, entrepôt incomplet).

## 4. Ce qui change (branche `agent/entrepot-fiable`)

| Élément | Rôle |
|---|---|
| `pipeline/entrepot_distant.py` | `diagnostic` (ce document) ; `lignee` (empreintes des entrées d'une sortie publiée, `pipeline/lignee.json`) ; `envoyer` (VPS : entrées d'origine vers `s3://<bucket public>/_entrees/objets/<sha256>`, index `_entrees/index.json`, réutilise `collecte/stockage.py` et rclone) ; `restaurer` (CI : GET seulement, anonyme ou signé SigV4 avec une clé en lecture seule, sha256 vérifié, date de collecte de la version remise dans le manifeste) ; `verifier` (reconstruction complète). La zone `_restreint` n'est jamais indexée ni restaurée. |
| `pipeline/garde_lignes.py` + `pipeline/pertes_autorisees.json` | aucun axe publié ne perd de lignes par rapport à HEAD sans motif et nombre écrits ; code 7 sinon |
| `.github/workflows/data.yml` | restauration depuis le bucket public après le cache (le cache reste un accélérateur) ; entrée `reconstruction` (recollecte de tout, vérification que chaque axe est produit, publication bloquée sinon) ; garde-fou de lignes avant le correctif |
| `deploy/collecte-hebdo.sh` | après l'orchestrateur (`OVMI_PIPELINE=1`), envoi des entrées au bucket public |
| `pipeline/entrees_lac.json` | entrées de `retraites` déclarées |
| `pipeline/lignee.json` | versions publiées de `retraites` (17/11), `niches` (16/11), `millesimes` (18/11) |
| tests `test_millesimes`, `test_retraites`, `test_reproductibilite` | deux productions identiques avec la date de la lignée ; comparaison aux sorties publiées seulement si l'entrepôt contient exactement les versions enregistrées (sinon saut avec motif) ; toutes les entrées déclarées vérifiées, pas seulement le catalogue |
| `tests/test_entrepot_distant.py` | lecture (bucket simulé : restauration, refus de `_restreint` et des chemins sortants, objet altéré rejeté, dates), signature, lignée, reconstruction, garde-fou, branchement dans `data.yml` |

## 5. Régénérables avant et après

- **Avant** (19/11) : aucune étape n'est reproductible à l'identique depuis une copie durable ; toutes dépendent d'une recollecte à la source le jour du passage, et les tests de reproductibilité de `millesimes`, `retraites` et `tests/test_reproductibilite.py` (niches) échouent dès que l'entrepôt local est présent.
- **Après ce commit, sans déploiement** : `retraites`, `niches` et `millesimes` sont reproduites et vérifiées contre leur lignée ; les tests sont déterministes (passent, ou sautent avec un motif nommant les fichiers en cause) ; une publication qui perdrait des lignes est bloquée ; la reconstruction complète échoue proprement au lieu de publier un état partiel.
- **Après déploiement par Benjamin** (docs/DEPLOIEMENT.md, partie 5) : les 48 étapes dont les entrées sont relevées deviennent régénérables depuis le bucket (zone publique) ; les 10 étapes à entrée restreinte le sont en entier sur le VPS ; les 17 étapes non relevées demandent un `tout.py inventorier` sur un entrepôt complet.

## 6. Règle n°0 : existant évalué

| Trouvaille | Verdict | Licence | Dernière version relevée | Usage |
|---|---|---|---|---|
| `collecte/stockage.py` (dépôt) : classe `Rclone`, `Config` | réutilisable tel quel | MIT du dépôt | 16/11/2026 | `envoyer` (VPS) |
| rclone | réutilisable tel quel | MIT | v1.76.0, 06/11/2026 (docs/STOCKAGE.md) | transferts vérifiés côté VPS |
| `pipeline/tout.py` (`entrepot`, `inventorier`, statuts) | réutilisable tel quel | MIT du dépôt | 19/11/2026 | recollecte, journal lu par `verifier` |
| `actions/cache` | réutilisable tel quel | MIT | v6.1.0 (épinglé) | gardé comme accélérateur |
| DuckDB httpfs | inspiration seulement | MIT | v2.0.0, 21/10/2026 | écarté en CI : extension téléchargée à l'exécution ; la signature SigV4 tient en 25 lignes de bibliothèque standard |
| DVC (Data Version Control, iterative/dvc, racheté par lakeFS) | inspiration seulement | Apache-2.0 | publications 2026 sur Zenodo | même principe (objets adressés par empreinte, fichier de lignée versionné) ; outil complet non retenu (dépendances lourdes, ne connaît pas la zone restreinte) |
| boto3, AWS CLI | écartés | Apache-2.0 | n/a | absents de `requirements.lock`, inutiles pour des GET |

Date du dernier commit des dépôts tiers non relevée : l'API GitHub des dépôts hors projet est refusée par le proxy de la session.
