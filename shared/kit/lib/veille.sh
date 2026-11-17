# Agents de veille (mises à jour, sécurité) : l'hôte collecte, l'agent analyse.
# (copie identique dans agent-updates et agent-securite, source : shared/kit/lib/veille.sh)
#
#   collect.py (root, sur l'hôte, stdlib seule) -> instantané stable, sans secret ni horodatage
#   push       -> <profil>/inbox/snapshot.txt dans la cible (lecture par l'agent)
#   timer      -> systemd ottho-agent-<agent>-collect.timer lance « agent.sh push »
#   cron Hermes du profil -> scripts/watch.py : NO_CHANGE (l'agent répond [SILENT]) ou CHANGE DETECTED + écart
# L'agent n'a ni terminal ni root : il propose les commandes, l'humain les tape.
# shellcheck shell=bash

veille_collect() { python3 "$KIT/collect.py" "$CONF"; }

veille_push() {
  need_conf
  local snap; snap="$(veille_collect)" || fail "Collecte en échec"
  printf '%s\n' "$snap" | t_write "$PHOME/inbox/snapshot.txt" 640
  printf '%s\n' "$(date -u +%s)" | t_write "$PHOME/inbox/collected_at" 640
  printf '%s\n' "${VEILLE_MAX_AGE:-10800}" | t_write "$PHOME/inbox/max_age" 640
}

veille_install_files() { # scripts du profil : watch.py, monitor.py, review.py + hook de périmètre
  local f
  for f in watch.py monitor.py review.py; do t_write "$PHOME/scripts/$f" 750 < "$KIT/lib/$f"; done
  t_write "$PHOME/hooks/ottho_perimeter.py" 750 < "$KIT/lib/perimeter_hook.py"
  t_exec mkdir -p "$PHOME/workspace" "$PHOME/inbox"
}

veille_timer() { # OnCalendar systemd
  local cal="$1" unit="ottho-agent-$AGENT-collect"
  cat >"/etc/systemd/system/$unit.service" <<EOF
[Unit]
Description=Ottho agent $AGENT : collecte de l'instantané (lecture seule) pour l'agent Hermes
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart=$KIT/agent.sh push
Nice=10
EOF
  cat >"/etc/systemd/system/$unit.timer" <<EOF
[Unit]
Description=Ottho agent $AGENT : collecte planifiée

[Timer]
OnCalendar=$cal
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now "$unit.timer" >/dev/null
  c_ok "Collecte planifiée ($cal) : systemctl list-timers $unit.timer"
}

veille_cron() { # nom expression mode(watch|review) prompt -> tâche Hermes du profil (conservée si elle existe déjà)
  # Hermes attend un nom de fichier relatif à <profil>/scripts/. Veille : --monitor-script (le modèle n'est appelé que si
  # la sortie change) ; repli --script watch.py (écart calculé par le kit, l'agent répond [SILENT]) sur un Hermes ancien.
  local name="$1" expr="$2" mode="$3" prompt="$4" existing out
  local -a opt
  existing="$(t_hermes cron list 2>/dev/null | grep -F -- "$name" || true)"
  if [ -n "$existing" ]; then
    c_ok "Tâche planifiée « $name » déjà présente (hermes -p $PROFILE cron list)"
    return 0
  fi
  if [ "$mode" = review ]; then opt=(--script review.py)
  elif t_hermes cron create --help 2>/dev/null | grep -q -- '--monitor-script'; then opt=(--monitor-script monitor.py)
  else opt=(--script watch.py); fi
  if out="$(t_hermes cron create "$expr" "$prompt" --name "$name" "${opt[@]}" --deliver telegram 2>&1)"; then
    c_ok "Tâche planifiée « $name » ($expr, ${opt[0]#--}) créée, livrée sur Telegram"
  else
    c_warn "Tâche « $name » non créée : $(printf '%s' "$out" | tail -1 | cut -c1-200)"
    return 1
  fi
}

veille_status() {
  need_conf
  local unit="ottho-agent-$AGENT-collect" at age
  echo "Agent      : $AGENT (profil $PROFILE, cible $KIND ${CONTAINER:-$HUSER})"
  echo "Collecte   : $(systemctl is-active "$unit.timer" 2>/dev/null || echo absente) ; prochaine : $(systemctl list-timers "$unit.timer" --no-legend 2>/dev/null | awk '{print $1, $2}')"
  at="$(t_exec cat "$PHOME/inbox/collected_at" 2>/dev/null || echo 0)"
  age=$(( $(date -u +%s) - ${at:-0} ))
  echo "Instantané : $( [ "${at:-0}" -gt 0 ] && echo "il y a $((age / 60)) min" || echo "jamais collecté")"
  echo "Bot        : TELEGRAM_BOT_TOKEN $(secret_present TELEGRAM_BOT_TOKEN), TELEGRAM_ALLOWED_USERS $(secret_present TELEGRAM_ALLOWED_USERS)"
  echo "Tâches     :"; t_hermes cron list 2>/dev/null | sed 's/^/  /' || echo "  (hermes cron list indisponible)"
}
