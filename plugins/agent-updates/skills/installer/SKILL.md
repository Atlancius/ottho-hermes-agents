---
name: installer
description: Installe et déploie l'agent mises à jour Hermes sur le VPS de la personne, adapté à son installation (cellule Ottho Hermes VPS, image Hostinger, conteneur maison ou Hermes natif) - profil sans terminal ni root, collecte quotidienne en lecture seule sur l'hôte, tâches Telegram quotidienne et du lundi, bot, test réel. Déclencheurs - installer l'agent mises à jour, surveiller les mises à jour de mon VPS, reprendre l'installation.
argument-hint: "[reprendre | étape N]"
---

# Agent mises à jour — installation guidée

Tu guides une personne (apprenant Ottho, pas forcément technique) jusqu'à un agent Hermes qui lui dit, sur Telegram, ce qui attend une mise à jour sur son VPS, le risque, et la commande exacte à taper. Tutoiement, une étape à la fois, validée avant la suivante.

Avant toute action, lis et applique **[les règles permanentes](../../references/regles.md)**. Condition : tu dois pouvoir lancer des commandes vers son ordinateur ou son VPS ; sinon, dis-le et n'invente aucun résultat.

## Comment il marche (à expliquer en 4 lignes)

- Chaque matin à 07:40, un petit programme root de l'hôte **lit** l'état du serveur (paquets en attente, sécurité, redémarrage, Docker, version de chaque Hermes face à la dernière publication) et le dépose dans le profil de l'agent. Il n'écrit rien d'autre que le cache `apt-get update` (désactivable).
- À 08:00, l'agent n'est réveillé que si quelque chose a changé ; il lit les notes de version et te propose quoi faire. Chaque lundi à 08:30, un bilan complet.
- L'agent n'a **ni terminal ni root** : il ne peut rien casser. C'est toi qui tapes les commandes qu'il propose.
- Si une mise à jour automatique de sécurité (`unattended-upgrades`) n'est pas active, il te propose de l'activer.

## Étape 0 — lanceur et cible

Racine du plugin : le dossier qui contient `skills/`, `scripts/` et `kit/` (Claude Code : `${CLAUDE_PLUGIN_ROOT}`). Depuis le dossier de travail de la personne :

```bash
bash "<racine du plugin>/scripts/agent-vps.sh" link
```

Ensuite tout passe par `bash .ottho-agents/updates …`. Si la sortie ne montre pas `state=.ottho-hermes/state.json`, demande l'accès SSH puis `bash .ottho-agents/updates target ssh utilisateur@adresse` (ou `target local` sur le VPS). Puis `bash .ottho-agents/updates check` : `SUDO_OK` et `PY_OK` exigés. Windows, Codex et ChatGPT : mêmes consignes que le plugin Ottho Hermes VPS (bash de Git, accès complet pour ce dossier).

## Étape 1 — envoyer le kit et repérer Hermes

```bash
bash .ottho-agents/updates upload
bash .ottho-agents/updates run detect
```

Choisis avec elle où vit le profil : la cellule de ses cadres (parcours Ottho Hermes VPS), son unique conteneur Hermes, ou `native:<utilisateur>`. L'agent ne lit que des notes de version publiques : il peut partager la cellule du maître. Nom de profil par défaut `updates` (unique sur le serveur). Le parcours Ottho prévoit déjà parfois un cadre « Sécurité » ou « Maintenance » : propose de lui donner ce rôle plutôt qu'un doublon (même nom de profil).

Modèle : le même que son agent maître par défaut ; fournisseur et identifiant vérifiés, jamais inventés.

## Étape 2 — installer

Annonce : un profil créé ou complété, garde-fous (terminal coupé, écriture limitée à `workspace/`), un service systemd de collecte en lecture seule, deux tâches planifiées. Rien n'est supprimé ; copies dans `/var/backups/ottho-agents/updates/`. Après accord :

```bash
bash .ottho-agents/updates run install --target <docker:conteneur|native:utilisateur> --owner "<Prénom>" [--provider <fournisseur> --model <identifiant>]
```

Une ligne `KO` arrête tout : explique, corrige, relance (rejouable). Si la création d'une tâche planifiée échoue (version de Hermes sans `cron create --script`), note-le et passe au skill `statut` après l'installation.

## Étape 3 — le bot, saisi par la personne

`bash .ottho-agents/updates cmd secret telegram` affiche la commande ; elle la tape elle-même : un bot dédié (BotFather → `/newbot`) et son identifiant Telegram numérique (@userinfobot). Clé de modèle propre au profil si besoin : `secret model <VARIABLE>` ou `secret login <fournisseur>`.

## Étape 4 — vérifier pour de vrai

```bash
bash .ottho-agents/updates run test
```

Attendu : instantané collecté et affiché (ce que l'agent recevra), deux tâches listées, bot présent. Vraie preuve : elle écrit au bot « qu'est-ce qui attend une mise à jour ? » et reçoit une réponse appuyée sur l'instantané. La première tâche du matin fera un bilan complet (premier instantané), les suivantes seront silencieuses tant que rien ne change.

## Fin

Mode d'emploi : lire Telegram le matin, appliquer une proposition à la fois (instantané du fournisseur ou sauvegarde avant), relancer `test` après une mise à jour pour que l'agent voie le nouvel état (`run push` suffit). Désactiver le rafraîchissement apt : `run set apt_refresh=non`.
