set -u
SRC="$1"
mkdir -p /root/essai-agents && cd /root/essai-agents
bash "$SRC/plugins/agent-updates/scripts/agent-vps.sh" link
bash "$SRC/plugins/agent-updates/scripts/agent-vps.sh" target local
bash .ottho-agents/updates check
bash .ottho-agents/updates upload
bash .ottho-agents/updates run detect
