#!/usr/bin/env bash
# Pont entre l'agent (Claude Code, Codex ou ChatGPT) et le kit de l'agent installé sur le VPS.
# Copie identique dans chaque plugin (source : shared/scripts/agent-vps.sh). Aucune commande ne transporte de secret.
#
# Cible : .ottho-hermes/state.json (parcours Ottho Hermes VPS) si présent, sinon .ottho-agents/target.json.
#
#   agent-vps.sh link                 crée le lanceur .ottho-agents/<agent> (chemin du plugin fixé)
#   agent-vps.sh target <ssh|local> [hôte]
#                                     enregistre la cible (ex. target ssh root@203.0.113.10) si aucun état n'existe
#   agent-vps.sh check                teste l'accès (SSH par clé, sudo sans mot de passe, Docker, Python)
#   agent-vps.sh upload               envoie le kit de l'agent sur le serveur (/opt/ottho-agents/<agent>)
#   agent-vps.sh run <commande…>      lance « sudo /opt/ottho-agents/<agent>/agent.sh <commande…> » sur la cible
#   agent-vps.sh cmd <commande…>      affiche la commande exacte à taper soi-même (secrets)
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT="$(cat "$PLUGIN_ROOT/kit/AGENT")"
REMOTE_DIR="/opt/ottho-agents/$AGENT"

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "Python 3 est requis sur cet ordinateur (https://www.python.org/downloads/)." >&2; exit 2; fi
py() { PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$PY" "$@"; }

state_file() {
  if [ -f .ottho-hermes/state.json ]; then echo .ottho-hermes/state.json
  elif [ -f .ottho-agents/target.json ]; then echo .ottho-agents/target.json
  else echo ""; fi
}

case "${1:-}" in
  link)
    mkdir -p .ottho-agents
    {
      printf '#!/usr/bin/env bash\n'
      printf '# Lanceur Ottho agent %s, régénéré à chaque démarrage. Ne pas modifier.\n' "$AGENT"
      printf 'exec bash %q "$@"\n' "$PLUGIN_ROOT/scripts/agent-vps.sh"
    } > ".ottho-agents/$AGENT"
    chmod +x ".ottho-agents/$AGENT" 2>/dev/null || true
    if [ -d .git ] && ! grep -qx '.ottho-agents/' .gitignore 2>/dev/null; then echo '.ottho-agents/' >> .gitignore; fi
    echo "LINK_OK $PLUGIN_ROOT agent=$AGENT state=$(state_file || true)"
    exit 0
    ;;
  target)
    mode="${2:?mode attendu : ssh ou local}"; host="${3:-}"
    [ "$mode" = local ] || [ -n "$host" ] || { echo "Hôte SSH attendu : target ssh utilisateur@adresse" >&2; exit 2; }
    [ -f .ottho-hermes/state.json ] && { echo "Cible déjà définie par le parcours Ottho Hermes VPS (.ottho-hermes/state.json) : rien à faire."; exit 0; }
    mkdir -p .ottho-agents
    py - "$mode" "$host" <<'PY'
import json, sys
mode, host = sys.argv[1], sys.argv[2]
user_is_root = host.split("@")[0] == "root" if "@" in host else False
json.dump({"target": {"mode": mode, "host": host, "user_is_root": user_is_root}}, open(".ottho-agents/target.json", "w"), indent=2)
print("TARGET_OK", mode, host)
PY
    exit 0
    ;;
esac

STATE="$(state_file)"
[ -n "$STATE" ] || { echo "Cible inconnue : lance d'abord « target ssh utilisateur@adresse » (ou « target local » sur le VPS)." >&2; exit 2; }
field() { py -c 'import json,sys; t=json.load(open(sys.argv[1])).get("target") or {}; print(t.get(sys.argv[2]) or "")' "$STATE" "$1"; }
MODE="$(field mode)"; HOST="$(field host)"
SUDO="sudo -n"; [ "$(field user_is_root)" = "True" ] && SUDO=""

remote() {
  if [ "$MODE" = local ]; then bash -c "$1"
  else ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 "$HOST" "$1"; fi
}
quote() { local out="" a; for a in "$@"; do out+=" $(printf '%q' "$a")"; done; printf '%s' "${out# }"; }

case "${1:-}" in
  check)
    if [ "$MODE" != local ]; then
      ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" true 2>/dev/null || { echo "SSH_KO : connexion par clé impossible vers $HOST"; exit 1; }
    fi
    remote "id -u; ($SUDO true 2>/dev/null && echo SUDO_OK) || echo SUDO_KO; command -v python3 >/dev/null && echo PY_OK || echo PY_KO; command -v docker >/dev/null && echo DOCKER_OK || echo DOCKER_ABSENT; . /etc/os-release; echo \"OS=\$PRETTY_NAME\""
    ;;
  upload)
    # Le kit est écrasé fichier par fichier (rien n'est supprimé) ; les réglages de l'élève vivent ailleurs (/etc/ottho-agents).
    remote "$SUDO install -d -m 755 $REMOTE_DIR"
    if [ "$MODE" = local ]; then
      tar -C "$PLUGIN_ROOT/kit" --exclude=__pycache__ -cf - . | $SUDO tar -C "$REMOTE_DIR" --no-same-owner -xf -
    else
      tar -C "$PLUGIN_ROOT/kit" --exclude=__pycache__ -cf - . | ssh -o BatchMode=yes "$HOST" "$SUDO tar -C $REMOTE_DIR --no-same-owner -xf -"
    fi
    remote "$SUDO chmod 755 $REMOTE_DIR/agent.sh"
    remote "$SUDO $REMOTE_DIR/agent.sh version"
    ;;
  run)
    shift
    remote "$SUDO $REMOTE_DIR/agent.sh $(quote "$@")"
    ;;
  cmd)
    shift
    if [ "$MODE" = local ]; then echo "sudo $REMOTE_DIR/agent.sh $(quote "$@")"
    else echo "ssh -t $HOST sudo $REMOTE_DIR/agent.sh $(quote "$@")"; fi
    ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
