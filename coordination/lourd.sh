#!/bin/bash
# Exécute une commande lourde en tenant l'un des créneaux machine (2 cœurs, 7 Go partagés par tous les agents).
# Usage : /home/claude/outils/lourd.sh <commande> [args...]   ex. lourd.sh bash -c 'cd web && npx vitest run tests/x.test.ts'
N=${OVMI_CRENEAUX:-$(nproc)}
while :; do
  for i in $(seq 1 "$N"); do
    exec 9>"/tmp/ovmi-renfort-creneau-$i.lock"
    if flock -n 9; then
      nice -n 5 "$@"; rc=$?
      exec 9>&-
      exit $rc
    fi
    exec 9>&-
  done
  sleep 3
done
