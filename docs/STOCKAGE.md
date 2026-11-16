# Stockage de l'entrepôt brut sur OVH Object Storage

L'entrepôt brut `data/lake/` (20 Go, 6 152 sources) ne tient plus sur un disque local et environ 124 Go de gros exports restent à collecter. La collecte tourne donc chaque semaine sur un VPS OVH (75 Go de disque, partagé) et range tout dans OVH Object Storage (S3 compatible, classe Standard). Le disque du VPS ne sert que de zone de transit : une source à la fois.

## Architecture

```
lundi 3 h (systemd timer, priorité basse)
  └─ deploy/collecte-hebdo.sh   (verrou, contrôle disque >= 10 Go, lots)
       └─ collecte/collecte.py --flux        pour chaque source :
            1. télécharger (reprise, requêtes conditionnelles ETag/Last-Modified)
            2. collecte/stockage.py : sha256 du brut identique à la version stockée ? -> rien n'est renvoyé
            3. collecte/conversion.py : tabulaire -> Parquet zstd (DuckDB), sinon original gardé
            4. rclone copyto --checksum (reprises, --bwlimit) puis vérification MD5 + taille
            5. effacement local, manifeste mis à jour
       └─ toutes les 25 sources et en fin de lot : manifeste sauvegardé dans les buckets
```

| Élément | Rôle | Réutilisé ou écrit |
|---|---|---|
| rclone | transfert S3, reprises, sommes de contrôle, limite de bande passante | réutilisé (MIT, v1.76.0 du 06/11/2026) |
| DuckDB | CSV/JSON vers Parquet zstd, lecture directe sur S3 (httpfs) | réutilisé (MIT, v2.0.0 du 21/10/2026) |
| openpyxl, xlrd | lecture XLSX / XLS (feuilles écrites en Parquet par pyarrow) | réutilisés |
| systemd | planification, priorité, confinement, alerte (OnFailure) | réutilisé |
| `collecte/conversion.py`, `collecte/stockage.py`, `deploy/` | la colle | écrits |

### Organisation des objets

```
s3://<bucket public>/<domaine>/<source>/<AAAA-MM-JJ>/<fichier>        données publiques
s3://<bucket privé>/<domaine>/<source>/<AAAA-MM-JJ>/<fichier>         personnes physiques (data/lake/_restreint)
s3://<bucket public>/_manifeste/manifest.json                         manifeste sans la zone restreinte
s3://<bucket privé>/_manifeste/manifest.json                          manifeste complet
s3://<bucket privé>/_manifeste/historique/manifest-<horodatage>.json.gz
```

- **Historique** : un nouveau dossier daté n'est créé que si le contenu brut change (sha256). Les versions précédentes restent ; le manifeste les liste (`stockage.versions`).
- **Pas de doublon** : contenu inchangé, rien n'est envoyé ; seule `stockage.verifie_le` change.
- **Séparation du privé** : tout fichier d'une source `personnes_physiques` ou situé sous `data/lake/_restreint/` part dans le bucket privé. Sans `OVMI_BUCKET_PRIVE`, il n'est pas envoyé et reste en local (`envoi_en_attente`), jamais dans le public. Un garde-fou refuse un bucket privé égal au public ou le contenant.
- **Reprise** : un envoi en échec garde le brut en local avec `envoi_en_attente` et l'erreur ; les objets déjà envoyés pour cette version incomplète sont supprimés ; le passage suivant renvoie.

### Champs ajoutés au manifeste (par fichier)

`objet` (URL de l'objet principal) et `stockage` : `sha256_brut`, `date_version`, `zone`, `format`, `converti`, `octets_avant`, `octets_apres`, `objets` (url, nom, octets, md5, lignes, vérification), `envoye_le`, `verifie_le`, `versions`, `conversion_erreurs` éventuelles. Le champ `sha256` existant reste l'empreinte du fichier brut publié.

## Conversion en Parquet

Règle : un fichier tabulaire (CSV/TSV, JSON tableau d'objets, NDJSON, XLS, XLSX, membres tabulaires d'un ZIP) est stocké en Parquet zstd (niveau 9) et l'original n'est pas gardé. Sont gardés tels quels : PDF, XML (DILA, budgets), tar.gz, 7z, Parquet déjà présents, JSON non tabulaires (JSON-stat Eurostat, enveloppes d'API), et tout fichier dont la conversion échoue (raison notée dans `conversion_erreurs`).

- Détection sur le contenu (octets magiques), pas sur l'extension (`.www_downlo`, `.csv_utf8`...).
- Fidélité : colonnes en texte (`all_varchar`) pour garder les zéros initiaux (codes INSEE, SIREN) et les montants au format français ; aucune ligne sautée (un préambule reste en lignes) ; lecture stricte : une ligne mal formée fait échouer la conversion et l'original est gardé. Fichiers Windows-1252/Latin-1 transcodés en UTF-8. Limite connue : une cellule vide devient NULL.
- XLS/XLSX : une table par feuille (`fichier.xlsx.<feuille>.parquet`), colonnes `c0, c1...`, sans interprétation d'en-tête.
- ZIP : membres tabulaires en Parquet, le reste regroupé dans `_reste.zip` (rien n'est perdu) ; l'archive est gardée entière si elle n'a pas de membre tabulaire ou si le résultat n'est pas plus petit (beaucoup de petits CSV compressent mieux en ZIP).
- NDJSON/JSON dont le schéma ne s'unifie pas : repli sur une colonne `json` par enregistrement (texte d'origine, requêtable avec `json_extract`).

### Gain mesuré (16/11/2026, 10 sources réelles du lake)

Commande : `python collecte/conversion.py --mesure --dest /tmp/mesure <10 sources>`.

| Source | Format | Fichiers | Avant | Après | Gain |
|---|---|---:|---:|---:|---:|
| europe_kohesio_2014_2020_fr | CSV | 1 | 143,6 Mo | 30,1 Mo | 79 % |
| datagouv__subventions-3 | CSV (petits) | 110 | 1,8 Mo | 0,8 Mo | 56 % |
| beneficiaires_ted_attributions_fr_2024 | NDJSON | 1 | 154,7 Mo | 27,2 Mo | 82 % |
| datagouv__adhesion-des-communes-a-un-epci | XLS | 16 | 119,3 Mo | 12,9 Mo | 89 % |
| drees__les-beneficiaires-de-l-aide-sociale-a-l-enfance | XLSX | 18 | 5,5 Mo | 1,7 Mo | 69 % |
| datagouv__le-revenu-de-solidarite-active-rsa | ZIP de CSV | 8 | 31,5 Mo | 7,6 Mo | 76 % |
| datagouv__fonds-des-cartes-de-chaleur (cambriolages) | ZIP shapefile | 7 | 19,9 Mo | 19,9 Mo | 0 % (gardé) |
| eu_gov_10a_exp_ue27 | JSON-stat | 58 | 234,8 Mo | 234,8 Mo | 0 % (non tabulaire) |
| datagouv__1900-2020-budget-commune-de-jouarre | PDF | 5 | 26,1 Mo | 26,1 Mo | 0 % |
| decisions_jorf_increments | tar.gz DILA | 14 | 24,9 Mo | 24,9 Mo | 0 % |
| **Total** | | 238 | **762,1 Mo** | **386,0 Mo** | **49 %** |

Sur les seuls fichiers tabulaires convertis : 476 Mo vers 100 Mo, **79 % de gain**. Durée : environ 1 min pour 762 Mo (2 cœurs, 1 Go de mémoire DuckDB).

### Volume estimé

- Lake actuel (20 Go) : CSV 3,8 Go, ZIP 4,8 Go, JSON 1,0 Go, XLS+XLSX 1,2 Go, NDJSON 0,5 Go convertibles ; Parquet 3,6 Go, PDF 2,1 Go, tar.gz 1,8 Go, XML et divers environ 1,4 Go gardés tels quels. En appliquant les taux mesurés (ZIP entre 25 et 60 % de reste, JSON entre 0 et 80 % de gain) : **12 à 14 Go** après conversion.
- 124 Go restant à collecter, en supposant la même composition : **75 à 90 Go**.
- Total : **90 à 105 Go** (environ 0,1 Tio), plus quelques Go par an d'historique (nouvelle version seulement si le contenu change).

## Coût

Prix relevés le 16/11/2026 sur la [page tarifs Public Cloud d'OVHcloud](https://www.ovhcloud.com/fr/public-cloud/prices/) (HT, facturation à l'heure, 730 h par mois) :

| Offre | Prix HT par Gio et par mois | Pour 1 Tio |
|---|---:|---:|
| Object Storage One Zone (1-AZ : Gravelines, Roubaix, Strasbourg), Standard | ~0,0070956 € | ~7,27 € |
| Object Storage Multi Zone (3-AZ, Paris), Standard, 50 premiers Tio | ~0,0139941 € | ~14,33 € |

Le trafic entrant et sortant et les requêtes API sont indiqués gratuits pour la classe Standard. Pour environ 100 Gio en One Zone Standard : **environ 0,70 € HT par mois** (moins de 9 € HT par an). Le chiffre de 7 € par To et par mois correspond bien à l'offre One Zone ; la 3-AZ coûte le double. Les tarifs ont été revus au 1er octobre 2026 : revérifier sur la page avant de décider.

## Procédure côté console OVH (à faire par toi)

1. **Projet Public Cloud** : console OVHcloud, onglet *Public Cloud*. Si aucun projet n'existe, *Créer un projet* (nom par exemple `ou-vont-mes-impots`, moyen de paiement, aucun service payant n'est créé à cette étape).
2. **Bucket public** : *Storage > Object Storage > Créer un bucket*. API S3, région France **1-AZ** (`GRA` Gravelines conseillé, ou `RBX`, `SBG`), classe **Standard**, nom par exemple `ovmi-lake-public`. Laisser la visibilité privée (rien n'est ouvert au public pour l'instant ; une ouverture en lecture pourra se décider plus tard, uniquement pour ce bucket). Le chiffrement côté serveur (SSE-OMK) peut être activé sans surcoût.
3. **Bucket privé** : même région et classe, nom par exemple `ovmi-lake-prive`. Il ne sera jamais rendu public. Activer le chiffrement SSE-OMK et, si proposé, le versioning.
4. **Utilisateur S3** : *Object Storage > Utilisateurs S3 > Créer un utilisateur* (description `ovmi-collecte`), rôle *ObjectStore operator* (lecture et écriture des objets). Récupérer la **clé d'accès** et la **clé secrète** (la secrète ne s'affiche qu'une fois). Si la console le permet, restreindre la politique de l'utilisateur aux deux buckets.
5. Noter le point d'accès : `s3.gra.io.cloud.ovh.net` et la région `gra` (adapter si autre région).

## Installation sur le VPS

```bash
curl -fsSLO https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/deploy/installer_vps.sh
sudo bash installer_vps.sh            # relançable ; installe sans rien collecter
sudo nano /etc/ovmi/stockage.env      # clés S3, OVMI_BUCKET_PUBLIC, OVMI_BUCKET_PRIVE (droits 640 root:ovmi)
sudo -u ovmi bash -c 'set -a; . /etc/ovmi/stockage.env; cd /var/lib/ovmi/ou-vont-mes-impots && /var/lib/ovmi/venv/bin/python collecte/stockage.py config'
sudo systemctl start ovmi-collecte.service   # premier passage à la main (sinon lundi 3 h)
journalctl -u ovmi-collecte -f
```

Le script crée l'utilisateur système `ovmi` (sans shell ni sudo), clone le dépôt public dans `/var/lib/ovmi/ou-vont-mes-impots`, crée un venv (requirements + `deploy/requirements-vps.txt`), installe le binaire officiel de rclone après contrôle de sa somme SHA256, l'extension DuckDB `httpfs`, le modèle `/etc/ovmi/stockage.env` et les unités `deploy/systemd/` (minuterie activée).

Ménagement du VPS partagé (`deploy/systemd/ovmi-collecte.service`) : `Nice=19`, ordonnancement `batch`, E/S `idle`, `CPUQuota=150%`, `MemoryHigh=1536M`, `MemoryMax=2G`, DuckDB limité à 1 Go et 2 cœurs, rclone `--bwlimit 8M` (`OVMI_BWLIMIT`), arrêt si moins de 10 Go libres (`OVMI_DISQUE_MIN_GO`), une seule collecte à la fois (verrou). Confinement : `ProtectSystem=strict`, seul `/var/lib/ovmi` est inscriptible, aucune capacité.

Alerte : toute sortie non nulle (75 disque, 78 configuration, 2 envoi en échec, 1 toutes sources en échec) marque l'unité en échec dans `systemctl status` et `journalctl`, et déclenche `ovmi-collecte-alerte.service`. Si `GITHUB_TOKEN` est rempli (jeton à grain fin limité au dépôt, permission *Issues: write*), une issue étiquetée `collecte-echec` est ouverte (ou commentée si une est déjà ouverte), sans les lignes mentionnant la zone restreinte ou un secret. Journaux : `journalctl -u ovmi-collecte` et `/var/lib/ovmi/journaux/` (12 derniers).

## Migration de l'entrepôt local existant

Depuis la machine qui contient `data/lake/` (même configuration par variables d'environnement, rclone installé) :

```bash
set -a; . ./stockage.env; set +a                         # fichier local hors dépôt, jamais versionné
python collecte/stockage.py config                       # buckets accessibles ?
python collecte/stockage.py migrer --essai               # liste ce qui partirait, n'envoie rien
python collecte/stockage.py migrer --limite 20 --garder-local   # premier essai réel, garde les fichiers
python collecte/stockage.py migrer                       # tout : envoie, vérifie, efface en local
```

Même logique que le flux : conversion, dédoublonnage par sha256, bucket privé pour `_restreint`, date de version = date de collecte de la source. Interrompue, la commande se relance sans renvoyer ce qui est déjà stocké. Copier ensuite `data/lake/manifest.json` sur le VPS n'est pas nécessaire : au premier passage, `collecte.py --flux` récupère le manifeste depuis le bucket s'il est absent en local.

## Interroger les données

```bash
python collecte/stockage.py requete deploy/requete_exemple.sql
```

En Python :

```python
import sys; sys.path.insert(0, "collecte")
from stockage import session_duckdb
con = session_duckdb()   # identifiants lus dans RCLONE_CONFIG_OVH_* (ou rclone config dump)
con.sql("SELECT count(*) FROM read_parquet('s3://ovmi-lake-public/etat/*/*/*.parquet')").show()
```

Les colonnes sont en texte : typer à la lecture (`TRY_CAST(replace(montant, ',', '.') AS DOUBLE)`). Chaque version est un dossier daté ; pour la dernière, filtrer sur le plus grand dossier (voir l'exemple SQL).

## Restauration

- **Manifeste** sur une machine neuve : `python collecte/stockage.py restaurer-manifeste` (automatique au premier `--flux`).
- **Une source** (version courante ou d'une date) : `python collecte/stockage.py restaurer <source> [--date AAAA-MM-JJ] [--dest dossier]`.
- **Tout un domaine ou tout le bucket**, avec rclone seul : `rclone copy ovh:ovmi-lake-public/etat ./restauration/etat --checksum`.
- Ce qui est restauré est la forme archivée : Parquet pour les fichiers tabulaires (l'original CSV/XLS n'est pas conservé, son sha256 reste dans le manifeste), fichier d'origine pour le reste. Un ZIP converti se restaure en Parquet + `_reste.zip`.
- Perte du VPS : réinstaller (`installer_vps.sh`), remettre `/etc/ovmi/stockage.env` ; rien d'autre n'est à sauvegarder, le manifeste est dans les buckets.

## Tests

`pytest -q collecte/tests` (sans réseau) : conversion (CSV fidèle, Latin-1, JSON/NDJSON, XLSX, PDF et CSV cassé gardés, ZIP), déduplication, historique, reprise après échec d'envoi, absence d'objet orphelin, séparation du privé, manifeste filtré et restauration, migration, branchement `--flux` de `collecte.py`, bout en bout avec un vrai rclone sur un remote de type `local` (sauté si rclone n'est pas installé), absence de secret dans les fichiers du dépôt.
