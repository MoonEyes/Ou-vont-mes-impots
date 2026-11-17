#!/usr/bin/env bash
# Collecte hebdomadaire en mode flux (lancee par ovmi-collecte.service, utilisateur ovmi).
# Collecte -> conversion Parquet -> envoi rclone -> verification -> effacement local, lot par lot.
# Sortie non nulle = echec visible dans journalctl et alerte (ovmi-collecte-alerte.service) :
#   75 espace disque insuffisant, 78 configuration absente, 2 envoi(s) en echec, 1 toutes sources en echec,
#   4 orchestrateur pipeline/tout.py en echec (phase facultative OVMI_PIPELINE=1).
# Journaux : $RACINE/journaux/collecte-AAAA-MM-JJ.log, compresses apres un jour, 12 gardes (OVMI_JOURNAUX_GARDES).
set -uo pipefail

RACINE=${OVMI_RACINE:-/var/lib/ovmi}
DEPOT=${OVMI_DEPOT:-$RACINE/ou-vont-mes-impots}
PY=${OVMI_PYTHON:-$RACINE/venv/bin/python}
MIN_GO=${OVMI_DISQUE_MIN_GO:-10}
GARDES=${OVMI_JOURNAUX_GARDES:-12}
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
    if git -C "$DEPOT" pull --ff-only -q; then
        log "code a jour : $(git -C "$DEPOT" log -1 --format='%h %s')"
    else
        log "mise a jour du code impossible, version actuelle conservee"
    fi
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

# Phase facultative : orchestrateur pipeline/tout.py (entrepot local des sources lues, puis regeneration de
# site/data dans l'ordre des dependances). Les sorties restent sur le VPS : la publication passe par GitHub
# (data.yml valide puis committe) ; ce service n'a aucun droit d'ecriture sur le depot ni sur Cloudflare.
if [[ "${OVMI_PIPELINE:-0}" == 1 ]] && (( code != 75 && code != 78 )); then
    if [[ ! -f "$DEPOT/pipeline/tout.py" ]]; then
        log "OVMI_PIPELINE=1 mais pipeline/tout.py absent de cette version du depot : phase sautee"
    elif (( $(libre_go) < MIN_GO )); then
        log "ARRET avant l'orchestrateur : $(libre_go) Go libres < ${MIN_GO} Go"
        code=75
    else
        BUDGET=${OVMI_PIPELINE_BUDGET:-18000}
        log "=== orchestrateur : entrepot (plafond ${OVMI_PIPELINE_PLAFOND_GO:-10} Go) puis passage (budget ${BUDGET} s)"
        (cd "$DEPOT" && "$PY" pipeline/tout.py entrepot --budget 3600 --plafond-go "${OVMI_PIPELINE_PLAFOND_GO:-10}") 2>&1 \
            | tee -a "$JOURNAL"
        (cd "$DEPOT" && "$PY" pipeline/tout.py --budget "$BUDGET") 2>&1 | tee -a "$JOURNAL"
        rc=${PIPESTATUS[0]}
        log "=== fin de l'orchestrateur : code $rc (detail : data/lake/_cache/tout/journal.json)"
        (( rc != 0 && code == 0 )) && code=4
    fi
fi

# Rotation : compresser les journaux des jours precedents, garder les $GARDES plus recents (.log et .log.gz).
find "$JOURNAUX" -maxdepth 1 -type f -name 'collecte-*.log' ! -name "$(basename "$JOURNAL")" -exec gzip -9f {} +
find "$JOURNAUX" -maxdepth 1 -type f -name 'collecte-*.log*' -printf '%T@ %p\n' | sort -rn | tail -n +"$((GARDES + 1))" \
    | cut -d' ' -f2- | xargs -r -d '\n' rm -f
log "collecte terminee, code $code, $(libre_go) Go libres"
exit "$code"
