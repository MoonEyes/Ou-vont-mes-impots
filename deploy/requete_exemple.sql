-- Interroger les Parquet du stockage objet sans rien telecharger (DuckDB + httpfs) :
--   python collecte/stockage.py requete deploy/requete_exemple.sql
-- ${OVMI_BUCKET_PUBLIC} est remplace par la variable d'environnement ; les identifiants S3 sont
-- ceux du remote rclone (RCLONE_CONFIG_OVH_*), jamais ecrits dans ce fichier.
-- Les colonnes sont stockees en texte (fidelite au fichier publie) : typer a la lecture (TRY_CAST).

-- 1. Inventaire : sources stockees par domaine, d'apres le manifeste public
WITH m AS (SELECT json AS j FROM read_json_objects('s3://${OVMI_BUCKET_PUBLIC}/_manifeste/manifest.json'))
SELECT j -> k ->> 'domaine' AS domaine, count(*) AS sources
FROM m, unnest(json_keys(j)) AS t(k)
GROUP BY ALL ORDER BY sources DESC;

-- 2. Derniere version d'un jeu (chaque collecte qui change le contenu cree un dossier AAAA-MM-JJ)
WITH v AS (
    SELECT *, regexp_extract(filename, '/(\d{4}-\d{2}-\d{2}[^/]*)/', 1) AS version
    FROM read_parquet('s3://${OVMI_BUCKET_PUBLIC}/europe/europe_kohesio_2014_2020_fr/*/*.parquet', filename = true)
)
SELECT postal_code[1:2] AS departement,
       count(*) AS operations,
       round(sum(TRY_CAST(replace(project_eu_budget, ',', '.') AS DOUBLE)) / 1e6, 1) AS budget_ue_meur
FROM v
WHERE version = (SELECT max(version) FROM v)
GROUP BY ALL ORDER BY budget_ue_meur DESC NULLS LAST
LIMIT 15;
