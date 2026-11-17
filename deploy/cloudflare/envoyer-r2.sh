#!/usr/bin/env bash
# Variante R2 : synchronise web/dist/data/local vers le bucket R2 (rclone, API S3 de R2), avant publier.sh --r2.
#   deploy/cloudflare/envoyer-r2.sh [--simuler]
# Variables (jamais versionnées ; jeton R2 « Object Read & Write » limité au seul bucket) :
#   OVMI_R2_BUCKET (défaut ovmi-donnees-local, comme wrangler.r2.toml)
#   RCLONE_CONFIG_R2_TYPE=s3  RCLONE_CONFIG_R2_PROVIDER=Cloudflare
#   RCLONE_CONFIG_R2_ENDPOINT=https://<ID_COMPTE>.r2.cloudflarestorage.com
#   RCLONE_CONFIG_R2_ACCESS_KEY_ID=…  RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=…
set -euo pipefail
ICI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE=$ICI/../../web/dist/data/local
BUCKET=${OVMI_R2_BUCKET:-ovmi-donnees-local}
opt=()
[[ "${1:-}" == --simuler ]] && opt=(--dry-run)
command -v rclone >/dev/null || { echo "ERREUR : rclone introuvable" >&2; exit 2; }
[[ -n "${RCLONE_CONFIG_R2_ACCESS_KEY_ID:-}" ]] || { echo "ERREUR : RCLONE_CONFIG_R2_* absentes" >&2; exit 2; }
[[ -d "$SOURCE" ]] || { echo "ERREUR : $SOURCE absent (npm run build dans web/)" >&2; exit 2; }
# --checksum : comparaison par empreinte (les dates changent à chaque construction) ; sync supprime les clés disparues
rclone sync "$SOURCE" "r2:$BUCKET/local" --checksum --s3-no-check-bucket --transfers 16 \
    --header-upload "Content-Type: application/json; charset=utf-8" "${opt[@]}" --stats-one-line -v
