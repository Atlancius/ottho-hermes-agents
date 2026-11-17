# Ottho Hermes Agents

Trois plugins Ottho Academy pour **Claude Code**, **Codex** et **ChatGPT** : chacun installe et déploie sur le VPS de l'élève un agent [Hermes Agent](https://hermes-agent.nousresearch.com) prêt à l'emploi, configuré avec ses propres accès et adapté à son installation.

| Plugin | L'agent | Ce qu'il ne peut pas faire |
|---|---|---|
| `agent-mail` | surveille la boîte mail en IMAP (IDLE), range chaque mail dans les dossiers de l'élève, étoile ce qui attend une réponse, écrit les brouillons, prévient sur Telegram (prospects, urgences), apprend les faits métier dictés au bot | envoyer un mail, lancer une commande, lire un fichier ou le web |
| `agent-updates` | suit chaque jour les mises à jour du système, de Docker et de Hermes, lit les notes de version, propose quoi faire et la commande exacte ; bilan le lundi | appliquer une mise à jour, lancer une commande, être root |
| `agent-securite` | surveille chaque heure conteneurs, ports, pare-feu, fail2ban, SSH, comptes, garde-fous des agents ; alerte avec preuve, gravité et correction ; revue le lundi | modifier le serveur, lancer une commande, tester une attaque |

Ce sont les versions partageables des agents mail, mises à jour et sécurité qui tournent en production chez l'auteur : même cœur (plugin IMAP, monitoring stable sans appel au modèle quand rien ne change), sans aucune donnée personnelle, et sans le canal root de production (remplacé par une collecte en lecture seule).

## Architecture commune

```
Élève (Claude Code / Codex / ChatGPT)           VPS
  skill installer ── agent-vps.sh ──SSH──► /opt/ottho-agents/<agent>/agent.sh (root)
                                              │  detect : cellule Ottho Hermes VPS, image Hostinger,
                                              │           conteneur maison ou Hermes natif
                                              ▼
                                  profil Hermes de l'agent (dans la cible choisie)
                                  ├── config.yaml : approvals smart, crons en deny, deny commune,
                                  │                 toolsets coupés, hook de périmètre (veille)
                                  ├── SOUL.md     : rendu depuis le gabarit, jamais écrasé s'il est retouché
                                  ├── .env        : secrets saisis par l'élève (masqué, 600), jamais lus par l'IA
                                  └── mail : plugins/mail-agent + mail-agent.yaml
                                      veille : scripts/monitor.py, inbox/snapshot.txt ◄── collect.py (root, systemd)
```

- **Mail** : plugin Hermes (plateforme `mail_inbox`, toolset `mail_agent`). Une session par mail entrant, le contenu du mail est encadré comme donnée non fiable, chaque outil est lié au seul mail de la session. Mode `shadow` d'abord.
- **Veille** (mises à jour, sécurité) : un collecteur root en lecture seule (`collect.py`, bibliothèque standard) produit un instantané **stable** (aucun horodatage, aucun secret) déposé dans le profil. La tâche Hermes utilise `cron create --monitor-script monitor.py` : le modèle n'est appelé que si l'instantané change (repli `--script watch.py` + `[SILENT]` sur un Hermes plus ancien). L'agent n'a ni terminal ni root : il propose, l'élève tape.

## Installation (élève)

Dépôt public : https://github.com/Atlancius/ottho-hermes-agents

```bash
claude plugin marketplace add Atlancius/ottho-hermes-agents && claude plugin install agent-mail@ottho-agents
codex plugin marketplace add https://github.com/Atlancius/ottho-hermes-agents.git && codex plugin add agent-mail@ottho-agents
```

(remplacer `agent-mail` par `agent-updates` ou `agent-securite`). Puis, dans Claude Code : `/agent-mail:installer` ; dans Codex ou ChatGPT : « Installe mon agent mail Hermes sur mon VPS ».

Prérequis : un VPS Linux avec Hermes Agent (idéalement installé par le plugin **Ottho Hermes VPS**, dont ces plugins reprennent la cible `.ottho-hermes/state.json`), un accès SSH par clé avec sudo, Telegram. Pour le mail : une boîte IMAP (Gmail avec mot de passe d'application, Hostinger, OVH, Ionos, Infomaniak…).

## Contenu du dépôt

| Chemin | Rôle |
|---|---|
| `plugins/agent-*/skills/` | parcours guidés (`installer`, `reglages` pour le mail, `statut`) |
| `plugins/agent-*/kit/` | kit serveur : `agent.sh`, `collect.py` (veille), plugin Hermes (mail), gabarits SOUL et réglages |
| `plugins/agent-*/scripts/agent-vps.sh` | pont SSH ou local entre l'IA et le kit |
| `shared/` | **source** des fichiers communs, recopiés dans chaque plugin par `python scripts/sync_shared.py` (un plugin s'installe seul) |
| `.claude-plugin/`, `.agents/plugins/`, `plugins/*/.claude-plugin`, `.codex-plugin`, `skills/*/agents/openai.yaml` | manifestes Claude Code, Codex, ChatGPT |
| `tests/` | tests hors ligne (`python -m unittest discover -s tests`) ; `tests/integration/` : banc réel sur un serveur Hermes d'essai |
| `docs/` | journal, décisions, registre des essais et des erreurs |

## Développer

```bash
python scripts/sync_shared.py                 # après toute modification de shared/
python -m unittest discover -s tests          # 19 tests, dont la recherche de données personnelles et les fins de ligne
```

Tout fichier est en LF (`.gitattributes`) : un script en CRLF casse bash sur le VPS.
