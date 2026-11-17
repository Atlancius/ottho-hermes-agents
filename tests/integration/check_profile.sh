#!/usr/bin/env bash
# Contrôle d'un profil de veille installé dans une cellule Docker (à lancer en root sur le serveur d'essai).
#   bash check_profile.sh <conteneur> <profil>
set -u
C="${1:?conteneur}"; P="/opt/data/profiles/${2:?profil}"
PY="$(docker exec "$C" sh -c 'test -x /opt/hermes/.venv/bin/python && echo /opt/hermes/.venv/bin/python || head -1 "$(command -v hermes)" | sed "s/^#!//"')"
X() { docker exec -u hermes -e HERMES_HOME=/opt/data "$C" "$@"; }
Xi() { docker exec -i -u hermes -e HERMES_HOME=/opt/data "$C" "$@"; }
echo "python de Hermes : $PY"
X "$PY" -c "
import yaml, json
c = yaml.safe_load(open('$P/config.yaml'))
a = c['approvals']
print('approvals', a['mode'], a['cron_mode'], a.get('single_query_mode'), 'deny:', len(a['deny']))
print('hook', json.dumps(c['hooks']['pre_tool_call'][0]))
print('disabled', ','.join(c['agent']['disabled_toolsets']))
print('model', c.get('model'), 'tz', c.get('timezone'))
"
X test -f "$P/shell-hooks-allowlist.json" && echo "allowlist présente"
hook() { printf '%s' "$1" | Xi "$PY" "$P/hooks/ottho_perimeter.py" >/dev/null; echo "$2 -> rc=$?"; }
hook '{"tool_name":"terminal","tool_input":{"command":"id"}}' "terminal (attendu 2)"
hook "{\"tool_name\":\"write_file\",\"tool_input\":{\"path\":\"$P/workspace/a.md\"}}" "écriture workspace (attendu 0)"
hook "{\"tool_name\":\"write_file\",\"tool_input\":{\"path\":\"$P/config.yaml\"}}" "écriture config (attendu 2)"
hook '{"tool_name":"read_file","tool_input":{"path":"/etc/hostname"}}' "lecture (attendu 0)"
a="$(X "$PY" "$P/scripts/monitor.py" | sha256sum)"; b="$(X "$PY" "$P/scripts/monitor.py" | sha256sum)"
[ "$a" = "$b" ] && echo "monitor.py : sortie stable" || echo "monitor.py : SORTIE INSTABLE"
X "$PY" "$P/scripts/monitor.py" | head -3
X ls -l "$P/inbox" "$P/scripts" "$P/hooks"
