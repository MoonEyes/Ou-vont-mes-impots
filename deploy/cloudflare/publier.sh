#!/usr/bin/env bash
# Publication du site sur Cloudflare (Workers Static Assets), depuis un poste, le VPS ou GitHub Actions.
#
#   deploy/cloudflare/publier.sh --verifier          # contrôles + simulation (aucun envoi, aucun identifiant requis)
#   deploy/cloudflare/publier.sh                     # contrôles + publication de web/dist
#   deploy/cloudflare/publier.sh --construire        # npm ci + npm run build dans web/ d'abord
#   deploy/cloudflare/publier.sh --r2                # variante : data/local servi depuis R2 (wrangler.r2.toml)
#
# Variables (jamais versionnées) :
#   CLOUDFLARE_API_TOKEN    jeton API à droits minimaux (docs/DEPLOIEMENT.md), requis sauf --verifier
#   CLOUDFLARE_ACCOUNT_ID   identifiant du compte (évite au jeton le droit de lister les comptes), requis sauf --verifier
#   OVMI_CF_MAX_FICHIERS    plafond de fichiers (défaut 20000, offre gratuite ; 100000 en offre payante)
#   OVMI_CF_SEUIL_ALERTE    part du plafond au-delà de laquelle un avertissement est affiché (défaut 80)
# Sortie : 0 publié (ou simulé), 1 contrôle en échec, 2 usage ou prérequis manquant.
set -euo pipefail

ICI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RACINE=$(cd "$ICI/../.." && pwd)
DIST=$RACINE/web/dist
MAX_FICHIERS=${OVMI_CF_MAX_FICHIERS:-20000}
SEUIL=${OVMI_CF_SEUIL_ALERTE:-80}
MAX_OCTETS=$((25 * 1024 * 1024))   # 25 Mio par fichier, toutes offres

verifier=0 construire=0 r2=0
for arg in "$@"; do
    case "$arg" in
        --verifier) verifier=1 ;;
        --construire) construire=1 ;;
        --r2) r2=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "option inconnue : $arg" >&2; exit 2 ;;
    esac
done

die() { echo "ERREUR : $*" >&2; exit "${2:-1}"; }

command -v node >/dev/null || die "node (>= 20.19) introuvable" 2
if (( ! verifier )); then
    [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]] || die "CLOUDFLARE_API_TOKEN absent (voir docs/DEPLOIEMENT.md)" 2
    [[ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]] || die "CLOUDFLARE_ACCOUNT_ID absent (voir docs/DEPLOIEMENT.md)" 2
fi

if (( construire )); then
    echo "==> construction (web/)"
    (cd "$RACINE/web" && npm ci --no-audit --no-fund && npm run build)
fi
[[ -f "$DIST/index.html" ]] || die "$DIST/index.html absent : lancer d'abord « npm run build » dans web/ (ou --construire)" 2

echo "==> wrangler (version figée par deploy/cloudflare/package-lock.json)"
(cd "$ICI" && npm ci --no-audit --no-fund --silent)
WRANGLER=$ICI/node_modules/.bin/wrangler

echo "==> fichiers de configuration dans web/dist"
install -m 644 "$RACINE/web/public/_headers" "$DIST/_headers"
install -m 644 "$RACINE/web/public/_redirects" "$DIST/_redirects"
if (( r2 )); then
    # data/local n'est pas envoyé avec les fichiers statiques : le Worker le lit dans R2 (envoyer-r2.sh)
    printf '%s\n' "data/local" > "$DIST/.assetsignore"
    CONFIG=$ICI/wrangler.r2.toml
else
    rm -f "$DIST/.assetsignore"
    CONFIG=$ICI/wrangler.toml
fi

echo "==> contrôle des limites Cloudflare"
# fichiers réellement envoyés : tout web/dist sauf les fichiers de configuration (et data/local en mode R2)
exclure=()
(( r2 )) && exclure=(-not -path "$DIST/data/local/*")
lister() {
    find "$DIST" -type f ! -name _headers ! -name _redirects ! -name .assetsignore "${exclure[@]}" -printf '%s %P\n'
}
fichiers=$(lister | wc -l)
# wrangler annonce « Read N files » en comptant aussi les dossiers : on compare ce total, plus prudent, au plafond
dossiers=$(find "$DIST" -mindepth 1 -type d "${exclure[@]}" | wc -l)
nb=$((fichiers + dossiers))
read -r taille_max fichier_max < <(lister | sort -n | tail -1)
total=$(lister | awk '{s += $1} END {printf "%.0f", s / 1048576}')
echo "    $fichiers fichiers + $dossiers dossiers = $nb entrées (plafond $MAX_FICHIERS), $total Mio au total"
echo "    plus gros : $fichier_max ($((taille_max / 1024)) Kio, plafond $((MAX_OCTETS / 1048576)) Mio)"
trop_gros=$(lister | awk -v m="$MAX_OCTETS" '$1 > m {print "    " $2 " (" int($1 / 1048576) " Mio)"}')
[[ -z "$trop_gros" ]] || die "fichier(s) au-delà de 25 Mio, refusés par Cloudflare :
$trop_gros
  => découper le fichier dans le pipeline, ou le servir depuis R2 (--r2, docs/DEPLOIEMENT.md)"
(( nb <= MAX_FICHIERS )) || die "$nb fichiers > plafond $MAX_FICHIERS : publier avec --r2 (data/local depuis R2, docs/DEPLOIEMENT.md)"
(( nb * 100 <= MAX_FICHIERS * SEUIL )) || echo "    AVERTISSEMENT : plus de $SEUIL % du plafond, prévoir --r2 (docs/DEPLOIEMENT.md)"
lignes_headers=$(grep -c '^/' "$RACINE/web/public/_headers" || true)
(( lignes_headers <= 100 )) || die "_headers : $lignes_headers règles > 100"

if (( verifier )); then
    echo "==> simulation (wrangler deploy --dry-run, rien n'est envoyé)"
    "$WRANGLER" deploy --config "$CONFIG" --dry-run
    echo "Contrôles réussis. Publication réelle : relancer sans --verifier, avec CLOUDFLARE_API_TOKEN et CLOUDFLARE_ACCOUNT_ID."
    exit 0
fi

echo "==> publication"
"$WRANGLER" deploy --config "$CONFIG" --message "site $(git -C "$RACINE" rev-parse --short HEAD 2>/dev/null || echo local)"
echo "Publié. Vérifier : curl -sI https://<adresse>/ | grep -i -e content-security -e cache-control"
