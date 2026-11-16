#!/usr/bin/env bash
# Collecte hebdomadaire en mode flux (lancee par ovmi-collecte.service, utilisateur ovmi).
# Collecte -> conversion Parquet -> envoi rclone -> verification -> effacement local, lot par lot.
# Sortie non nulle = echec visible dans journalctl et alerte (ovmi-collecte-alerte.service) :
#   75 espace disque insuffisant, 78 configuration absente, 2 envoi(s) en echec, 1 toutes sources en echec.
set -uo pipefail

RACINE=${OVMI_RACINE:-/var/lib/ovmi}
DEPOT=${OVMI_DEPOT:-$RACINE/ou-vont-mes-impots}
PY=${OVMI_PYTHON:-$RACINE/venv/bin/python}
MIN_GO=${OVMI_DISQUE_MIN_GO:-10}
JOURNAUX=$RACINE/journaux
mkdir -p "$DEPOT/data/lake" "$JOURNAUX"
JOURNAL=$JOURNAUX/collecte-$(date +%F).log

exec 9>"$RACINE/.collecte.lock"
if ! flock -n 9; then
    echo "une collecte est deja en cours, rien a faire"
    exit 0
fi

libre_go() { df -P -BG "$DEPOT/data/lake" | awk 'NR==2 {gsub("G", "", $4); print $4}'; }

log() { echo "$(date '+%F %T') $*" | tee -a "$JOURNAL"; }

if (( $(libre_go) < MIN_GO )); then
    log "ARRET : $(libre_go) Go libres < ${MIN_GO} Go requis sur $DEPOT/data/lake"
    exit 75
fi

if [[ "${OVMI_MAJ_AUTO:-0}" == 1 ]]; then
    git -C "$DEPOT" pull --ff-only -q && log "code a jour : $(git -C "$DEPOT" log -1 --format='%h %s')" \
        || log "mise a jour du code impossible, version actuelle conservee"
fi

code=0
IFS=';' read -ra LOTS <<< "${OVMI_LOTS:---lourd}"
for lot in "${LOTS[@]}"; do
    [[ -z "${lot// /}" ]] && continue
    if (( $(libre_go) < MIN_GO )); then
        log "ARRET avant le lot [$lot] : $(libre_go) Go libres < ${MIN_GO} Go"
        code=75
        break
    fi
    log "=== lot : $lot"
    # shellcheck disable=SC2086
    "$PY" "$DEPOT/collecte/collecte.py" --flux --reserve-go "$MIN_GO" $lot 2>&1 | tee -a "$JOURNAL"
    rc=${PIPESTATUS[0]}
    log "=== fin du lot [$lot] : code $rc"
    (( rc > code )) && code=$rc
    (( rc == 78 )) && break  # configuration absente : inutile de continuer
done

# garder les 12 derniers journaux
ls -1t "$JOURNAUX"/collecte-*.log 2>/dev/null | tail -n +13 | xargs -r rm -f
log "collecte terminee, code $code, $(libre_go) Go libres"
exit "$code"
