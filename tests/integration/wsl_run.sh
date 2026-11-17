#!/usr/bin/env bash
# Banc d'essai : déroule l'installation réelle d'un agent sur un serveur Hermes d'essai, en root, en mode « local ».
#   bash wsl_run.sh <dossier du dépôt> <agent: mail|updates|securite> <commande du lanceur…>
# Exemple : bash wsl_run.sh /mnt/c/…/ottho-hermes-agents securite run install --target docker:hermes-equipes --profile essaisecurite
set -u
SRC="${1:?dépôt}"; AGENT="${2:?agent}"; shift 2
mkdir -p /root/essai-agents && cd /root/essai-agents || exit 1
bash "$SRC/plugins/agent-$AGENT/scripts/agent-vps.sh" link >/dev/null
[ -f .ottho-agents/target.json ] || bash "$SRC/plugins/agent-$AGENT/scripts/agent-vps.sh" target local >/dev/null
bash ".ottho-agents/$AGENT" upload >/dev/null || exit 1
bash ".ottho-agents/$AGENT" "$@" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
