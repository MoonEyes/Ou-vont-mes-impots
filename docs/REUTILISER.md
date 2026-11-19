# Réutiliser les données

Ce document s'adresse aux personnes qui veulent reprendre les données du site (journalistes, chercheurs, associations, portails de données). Le site est **citoyen et non officiel** : il retraite des jeux publics ouverts, il ne produit pas de statistique officielle. Pour un chiffre de référence, la source d'origine citée dans chaque fichier fait foi.

## 1. Ce qui est publié

`site/data/` contient environ 4 200 fichiers JSON et 3 tables CSV, régénérés chaque lundi par le pipeline (`pipeline/tout.py`) : budget de l'État (exécution 2024, LFI 2025, nature PLF 2025), administrations publiques (Eurostat COFOG), recettes, déficit, dette, Sécurité sociale, prélèvements et leur affectation, dépenses fiscales, collectivités (« Près de chez moi »), Union européenne, bénéficiaires nommés (personnes morales uniquement), décisions sur les crédits, traçabilité de chaque euro, contrôle (juridictions financières, HATVP), opérateurs de l'État, comparaison européenne.

Les métadonnées de réutilisation sont dans `docs/datapackage/` :

| Fichier | Contenu |
|---|---|
| `datapackage.json` | [Frictionless Data Package v2](https://datapackage.org/) : une ressource par famille de fichiers, schéma JSON, licence, sources, millésimes |
| `fichiers.csv` | inventaire : chaque fichier, sa famille (`ressource`), son schéma, son URL de téléchargement |
| `sources.csv` | lignée : chaque jeu public lu par chaque étape du pipeline, avec son éditeur, son URL et sa licence |
| `datapackage.json`, champ `versions_sources` d'une ressource | version exacte des fichiers d'entrée de l'étape qui l'a produite, quand elle est relevée dans `pipeline/lignee.json` : chemin dans l'entrepôt, sha256, taille, source du catalogue, date de collecte, date de production de l'étape |
| `dcat.jsonld` | description DCAT-AP (moissonnage par data.gouv.fr et les portails européens) |
| `schemaorg.jsonld` | description schema.org `Dataset` |

Ils sont produits par `python pipeline/datapackage.py` (reproductible ; `--controle` dit s'ils sont à jour, `--verifier` lance la validation Frictionless).

## 2. Télécharger

| Quoi | URL stable |
|---|---|
| Un fichier JSON | `https://mooneyes.github.io/Ou-vont-mes-impots/data/<chemin>` (ex. `.../data/arbre/racine.json`) |
| Une table CSV | `https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/site/data/<chemin>` (les CSV ne sont pas servis par le site) |
| Le descripteur et l'inventaire | `https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/docs/datapackage/datapackage.json` (et `fichiers.csv`, `sources.csv`) |
| Tout le jeu | dépôt `https://github.com/MoonEyes/Ou-vont-mes-impots`, dossier `site/data/` |
| Les schémas | `https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/docs/schemas/<nom>.schema.json` |

Pour récupérer seulement les données, sans l'historique ni le reste du dépôt :

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/MoonEyes/Ou-vont-mes-impots.git
cd Ou-vont-mes-impots && git sparse-checkout set site/data docs/datapackage docs/schemas
```

Un instantané daté s'obtient en citant le commit (`git log -1 --format=%H -- site/data`) : les URL ci-dessus suivent toujours la dernière version. L'état du dernier passage de mise à jour (étapes produites, conservées faute de source joignable) est dans `mise_a_jour.json`.

## 3. Structure

- **Familles.** Chaque ressource du `datapackage.json` correspond à un motif du contrat d'interface (ex. `site/data/tracabilite/programme_*.json`) ; `path` désigne le premier fichier de la famille, la liste complète est dans `fichiers.csv`. Le sens de chaque champ est dans `docs/contrat_interface.md`, le format exact dans `docs/schemas/` (JSON Schema 2020-12, définitions partagées dans `commun.schema.json`).
- **En-tête.** Tout fichier JSON porte `millesime` (chaîne lisible, ex. « Exécution 2024 ») et `source` (jeu et pièce d'origine), souvent `unite` et `avertissement`. `meta.json` fait exception : `millesime` y est un objet.
- **Unités.** Milliards d'euros (`md`) pour le budget de l'État et Eurostat ; euros (`*_eur`) pour les fichiers par programme ; le champ `unite` le rappelle. Les montants personnels du simulateur ne sont pas publiés (calcul dans le navigateur).
- **Absence.** `null` = donnée absente à la source, jamais zéro ; une clé absente = niveau non applicable.
- **Liens internes.** Les champs `fichier` sont relatifs à `site/data/` (sauf `vie_politique/annees.json`, relatif à `vie_politique/`).
- **Identifiants.** Programmes LOLF sur trois chiffres en chaîne (`"150"`), codes INSEE en chaîne, SIREN sur neuf chiffres en chaîne : à lire comme texte pour garder les zéros initiaux.

## 4. Exemples

### DuckDB

Un fichier en ligne (DuckDB charge seul l'extension `httpfs`) :

```sql
-- Grands postes du budget de l'État, exécution 2024, en milliards d'euros
SELECT g.nom AS grand_poste, round(g.md, 1) AS md
FROM (SELECT unnest(enfants) AS g
      FROM read_json('https://mooneyes.github.io/Ou-vont-mes-impots/data/arbre/racine.json',
                     maximum_object_size = 50000000))
ORDER BY md DESC;

-- Part de chaque programme dont le destinataire est publié (traçabilité)
SELECT p.id, p.libelle, round(p.total_eur / 1e9, 2) AS md, p.taux_tracabilite_pct, p.approche
FROM (SELECT unnest(programmes) AS p
      FROM read_json('https://mooneyes.github.io/Ou-vont-mes-impots/data/tracabilite/resume.json'))
ORDER BY md DESC LIMIT 10;
```

Une famille entière, sur une copie locale (le site ne liste pas ses dossiers : les motifs `*` ne marchent qu'en local). Les fichiers d'une famille ont des structures imbriquées variables ; `read_json_objects` évite l'inférence de schéma, coûteuse en mémoire :

```sql
SELECT regexp_extract(filename, 'programme_(\d+)', 1) AS programme,
       json ->> '$.millesime' AS millesime,
       CAST(json ->> '$.parts.non_publie.pct' AS DOUBLE) AS non_publie_pct
FROM read_json_objects('site/data/tracabilite/programme_*.json', filename = true,
                       maximum_object_size = 100000000)
ORDER BY non_publie_pct DESC NULLS LAST;

-- Tables CSV : garder les identifiants en texte
SELECT source, groupe, siren, denomination, montant_eur
FROM read_csv('https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/site/data/beneficiaires/beneficiaires_publies.csv',
              types = {'siren': 'VARCHAR', 'categorie_juridique': 'VARCHAR'})
WHERE groupe = 'ensemble' ORDER BY montant_eur DESC LIMIT 20;

-- Licences des jeux d'origine par étape du pipeline
SELECT etape, licence_normalisee, count(*) AS jeux
FROM read_csv('https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/docs/datapackage/sources.csv')
GROUP BY ALL ORDER BY etape;
```

### Python

```python
import json
import urllib.request

import pandas as pd

SITE = "https://mooneyes.github.io/Ou-vont-mes-impots/data/"
DEPOT = "https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/"

with urllib.request.urlopen(SITE + "tracabilite/resume.json") as r:
    resume = json.load(r)
print(resume["millesime"], "|", resume["source"])
programmes = pd.DataFrame(resume["programmes"])

effectifs = pd.read_csv(DEPOT + "site/data/effectifs/effectifs.csv", dtype={"programme": str})
inventaire = pd.read_csv(DEPOT + "docs/datapackage/fichiers.csv")
urls_communes = inventaire.loc[inventaire["ressource"] == "communes", "url"]

# Avec frictionless (pip install frictionless) : ressources, licences, sources
from frictionless import Package
paquet = Package(DEPOT + "docs/datapackage/datapackage.json")
for res in paquet.resources[:5]:
    print(res.name, res.licenses[0]["name"], res.path)
```

### R

```r
library(jsonlite)
library(readr)

site  <- "https://mooneyes.github.io/Ou-vont-mes-impots/data/"
depot <- "https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/"

resume <- fromJSON(paste0(site, "tracabilite/resume.json"))
programmes <- resume$programmes          # data.frame, une ligne par programme

benef <- read_csv(paste0(depot, "site/data/beneficiaires/beneficiaires_publies.csv"),
                  col_types = cols(siren = col_character(), categorie_juridique = col_character()))
inventaire <- read_csv(paste0(depot, "docs/datapackage/fichiers.csv"))
sources <- read_csv(paste0(depot, "docs/datapackage/sources.csv"))
```

## 5. Limites et précautions de lecture

**Tracé, approché, non publié.** Dans `tracabilite/`, chaque euro d'un programme est rangé dans une seule part : `beneficiaire_identifie` (bénéficiaire nommé par une source publique, ou catégorie fixée par la loi), `nominatif_par_choix` (rémunérations : la catégorie d'agents est publiée, pas les noms), `anonyme_par_nature` (charge de la dette), `non_publie` (le reste). Une part `approche` rapproche des montants de millésimes différents (écart et raison indiqués) ; seule une part `exact` compare des chiffres de la même année. « Non publié » signifie que les sources ouvertes ne nomment pas le destinataire, pas que la dépense est inconnue de l'administration.

**Doubles comptes.**
- Bénéficiaires : les groupes se recoupent (ex. France 2030 : groupe `ensemble` et groupe par opérateur) ; une même personne morale peut figurer dans plusieurs groupes et plusieurs programmes. Ne pas additionner entre groupes ; les totaux de contrôle sont dans `beneficiaires/index.json`.
- Administrations publiques : la somme des secteurs (État, collectivités, Sécurité sociale) dépasse le total consolidé, à cause des transferts entre administrations ; l'écart est publié dans `meta.json` (`controle.arbre_administrations`).
- Exonérations de cotisations compensées par l'État : déjà comptées dans la dépense de l'État, elles ne s'ajoutent pas aux dépenses fiscales (`niches/sociales.json`).
- Prélèvements sur recettes (collectivités, Union européenne) : présentés à part dans l'arbre de l'État ; ne pas les ajouter une seconde fois aux dotations des collectivités ou à la contribution européenne.

**Millésimes.** Chaque fichier dit son millésime ; ils diffèrent d'un bloc à l'autre (exécution 2024 par défaut, LFI 2025, nature d'après le PLF 2025 qui est un projet et non un budget voté, ETPT LFI 2023 rapprochés du titre 2 exécuté en 2024, collectivités par exercice, Eurostat avec années provisoires). Comparer deux fichiers suppose de vérifier leurs millésimes. Les champs `millesimes` du `datapackage.json` les résument par famille.

**Conventions.** Comptabilité budgétaire (État, crédits de paiement) et comptabilité nationale (administrations publiques, Eurostat, Insee) ne sont jamais mélangées dans un même total. Les remboursements et dégrèvements d'impôts sont retirés de la dépense de l'État par convention (montant et motif dans `meta.json`). Tout montant écarté est publié avec sa raison.

**Personnes.** Seules les personnes morales sont nommées (catégorie juridique 2xxx à 9xxx) ; entrepreneurs individuels et lignes sans SIREN valide sont agrégés. Seule exception : les candidats des comptes de campagne publiés par la CNCCFP ou au Journal officiel, avec une liste restreinte de champs. Une réutilisation ne doit pas chercher à réidentifier les montants agrégés.

**Mises à jour.** Les fichiers changent chaque semaine quand une source change ; une étape dont la source est injoignable garde sa version précédente (`mise_a_jour.json`). Les noms de fichiers et de champs suivent le versionnage du contrat (`docs/contrat_interface.md`) : un renommage passe par une version majeure.

## 6. Conditions de réutilisation

- **Données dérivées** (`site/data`) : [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/), réutilisation libre, y compris commerciale, sous réserve de mentionner la source.
- **Exception ODbL.** Quand une étape du pipeline lit au moins un jeu publié sous [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) (certaines données URSSAF, publications de la Cour des comptes 2011-2016, jeux de subventions de collectivités), les ressources qu'elle produit sont déclarées sous ODbL dans le `datapackage.json` (champ `licence_motif`) : une base de données dérivée publiée doit alors rester sous ODbL. La lignée étant connue par étape et non par fichier, ce classement est prudent ; `sources.csv` permet de vérifier jeu par jeu.
- **Sources d'origine** : leur licence est dans `sources.csv` (telle que publiée et normalisée) et dans le champ `sources` de chaque ressource : Licence Ouverte 2.0 pour la plupart des jeux français, conditions Eurostat (réutilisation libre avec mention), décision 2011/833/UE pour les données de la Commission, documents administratifs publics, et quelques jeux de collectivités sans licence précisée par leur éditeur.
- **Code** (pipeline, site) : licence MIT (`LICENSE`).

Mention suggérée : « Source : Où vont mes impôts (projet citoyen), d'après *[source citée dans le fichier]*, *[millésime]*, https://mooneyes.github.io/Ou-vont-mes-impots/ ». Une réutilisation ne doit pas laisser croire à un caractère officiel des données ni à une approbation par les administrations sources.

## 7. Signaler une erreur

Ouvrir une issue sur https://github.com/MoonEyes/Ou-vont-mes-impots/issues en indiquant : le fichier (chemin dans `site/data/`), le champ et la valeur en cause, la valeur attendue et la source publique qui la donne (lien, page, millésime). Une erreur de données se corrige dans le code du pipeline, jamais à la main dans `site/data` (`CONTRIBUTING.md`). Les corrections sont publiées au passage hebdomadaire suivant.
