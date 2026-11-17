# Décisions (ADR) — Ottho Hermes Agents

## ADR-001 — Un dépôt, une marketplace `ottho-agents`, trois plugins (2026-11-17)

- **Contexte** : trois agents à partager sur la marketplace Ottho Academy, à côté du plugin `ottho-hermes-vps` (marketplace `ottho`).
- **Décision** : un dépôt, marketplace `ottho-agents`, plugins `agent-mail`, `agent-updates`, `agent-securite`, chacun autonome (une fiche marketplace par agent). Les fichiers communs vivent dans `shared/` et sont recopiés par `scripts/sync_shared.py` ; un test échoue si une copie diverge.
- **Écartées** : un seul plugin à trois agents (une seule fiche, installation de tout pour un seul besoin) ; ajout dans `ottho-hermes-vps` (alourdit le parcours d'installation, cycle de version commun) ; nom de marketplace `ottho` (collision avec celle d'Ottho Hermes VPS chez l'élève).

## ADR-002 — Agents de veille sans root : collecte hôte en lecture seule (2026-11-17)

- **Contexte** : en production chez l'auteur, les agents de veille disposent d'un canal root dont chaque commande est validée par un humain. Les règles d'Ottho Hermes VPS interdisent tout root aux agents des élèves.
- **Décision** : un collecteur root (`collect.py`, bibliothèque standard, timer systemd) dépose un instantané stable dans le profil ; l'agent n'a ni terminal ni root (toolsets coupés + hook `ottho_perimeter.py` fail-closed), il propose les commandes que l'élève tape.
- **Écartées** : reproduire ce canal root (surface d'attaque, complexité, contraire aux règles du kit élève) ; donner `docker`/`sudo` à l'agent (inacceptable).
- **Conséquence** : seule action d'écriture de la collecte : `apt-get update` (cache), désactivable (`set apt_refresh=non`).

## ADR-003 — Mode moniteur natif de Hermes, repli script + [SILENT] (2026-11-17)

- **Contexte** : vérifié sur Hermes v0.22.2 : `cron create` accepte `--monitor-script` (le modèle n'est pas appelé si la sortie est identique) et `--script` n'accepte qu'un nom de fichier relatif à `<profil>/scripts/`.
- **Décision** : veille = `--monitor-script monitor.py` (sortie stable : état de la collecte + instantané) ; revue hebdomadaire = `--script review.py`. Repli automatique `--script watch.py` (écart calculé par le kit, `NO_CHANGE` → `[SILENT]`) si `--monitor-script` est absent de l'aide.
- **Écartées** : `--script` seul partout (le modèle tourne à chaque échéance, coût) ; `--no-agent` (plus d'analyse).

## ADR-004 — Agent mail générique dérivé de l'agent mail de production (2026-11-17)

- **Décision** : même plugin (IMAP IDLE, une session par mail, outils liés au mail de la session, jamais d'envoi), rendu générique : marques et registres définis dans `mail-agent.yaml`, propriétaire nommé, serveur IMAP au choix, relais de transfert configurables, base de connaissances = dossier Markdown copié dans le profil (`knowledge-sync`) avec exclusion `private: true`, faits dictés (`owner_fact_*`). Noms : plateforme `mail_inbox`, toolset `mail_agent`, en-tête `X-Mail-Agent-Ref`, variables `MAIL_AGENT_*`.
- **Écartées** : montage d'un coffre Obsidian en volume (exige de modifier le compose de la cellule) ; OAuth Google/Microsoft (hors périmètre v1).

## ADR-005 — Cible détectée, jamais supposée (2026-11-17)

- **Décision** : `agent.sh detect` liste les conteneurs qui contiennent `hermes` et les installations natives (`~/.hermes`) ; l'élève choisit `docker:<conteneur>` ou `native:<utilisateur>`. Le profil est créé par `hermes profile create` (modèle hérité de la cellule) ou complété s'il existe ; rien n'est effacé, chaque fichier remplacé est sauvegardé dans `/var/backups/ottho-agents/`.
- **Écartée** : imposer la topologie Ottho Hermes VPS (exclurait les images Hostinger et les installations maison).
