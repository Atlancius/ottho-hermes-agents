#!/usr/bin/env bash
# Met en pause, sur le serveur d'essai, les tâches et minuteries créées par le banc (rien n'est supprimé).
#   bash pause_bench.sh <conteneur> <profil>…      (en root)
# Reprise : hermes -p <profil> cron resume <id> ; systemctl enable --now ottho-agent-<agent>-collect.timer
set -u
C="${1:?conteneur}"; shift
for p in "$@"; do
  for id in $(docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes -p "$p" cron list 2>/dev/null | grep -oE '^ +[0-9a-f]{12}' ); do
    docker exec -u hermes -e HERMES_HOME=/opt/data "$C" hermes -p "$p" cron pause "$id" >/dev/null && echo "pause $p/$id"
  done
done
for t in ottho-agent-updates-collect.timer ottho-agent-securite-collect.timer; do
  systemctl disable --now "$t" >/dev/null 2>&1 && echo "minuterie arrêtée : $t"
done
