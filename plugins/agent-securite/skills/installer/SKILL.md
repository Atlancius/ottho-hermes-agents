---
name: installer
description: Installe et déploie l'agent sécurité Hermes sur le VPS de la personne, adapté à son installation (cellule Ottho Hermes VPS, image Hostinger, conteneur maison ou Hermes natif) et à ses accès (sources SSH connues) - profil sans terminal ni root, collecte horaire en lecture seule, veille horaire et revue du lundi sur Telegram, test réel. Déclencheurs - installer l'agent sécurité, surveiller la sécurité de mon VPS, reprendre l'installation.
argument-hint: "[reprendre | étape N]"
---

# Agent sécurité — installation guidée

Tu guides une personne (apprenant Ottho, pas forcément technique) jusqu'à un agent Hermes qui surveille son VPS et ses agents, et l'alerte sur Telegram avec la preuve et la correction à appliquer. Tutoiement, une étape à la fois, validée avant la suivante.

Avant toute action, lis et applique **[les règles permanentes](../../references/regles.md)**. Condition : tu dois pouvoir lancer des commandes vers son ordinateur ou son VPS ; sinon, dis-le et n'invente aucun résultat.

## Comment il marche (à expliquer en 4 lignes)

- Chaque heure, un petit programme root de l'hôte **lit** la posture : conteneurs (privilégiés, réseau hôte, socket Docker), ports ouverts, pare-feu, fail2ban, SSH (réglages, clés autorisées, connexions acceptées), comptes à privilèges, services en échec, disques, garde-fous de tes agents Hermes. Aucun secret n'est lu : des noms, des états et des empreintes.
- L'agent n'est réveillé que si quelque chose a changé ; il classe l'écart (critique à basse), donne la preuve, la cause probable et la commande de correction. Chaque lundi à 09:00, une revue complète.
- L'agent n'a **ni terminal ni root** : il ne peut rien modifier. Tu restes la seule personne qui agit.
- Il ne fait aucun test d'attaque.

## Étape 0 — lanceur et cible

Racine du plugin : le dossier qui contient `skills/`, `scripts/` et `kit/` (Claude Code : `${CLAUDE_PLUGIN_ROOT}`). Depuis le dossier de travail :

```bash
bash "<racine du plugin>/scripts/agent-vps.sh" link
```

Ensuite tout passe par `bash .ottho-agents/securite …`. Sans `state=.ottho-hermes/state.json`, demande l'accès SSH puis `target ssh utilisateur@adresse` (ou `target local`). Puis `check` : `SUDO_OK` et `PY_OK` exigés.

## Étape 1 — envoyer le kit et repérer Hermes

```bash
bash .ottho-agents/securite upload
bash .ottho-agents/securite run detect
```

Choisis avec elle où vit le profil (cellule des cadres, son unique conteneur Hermes, ou `native:<utilisateur>`). Si le parcours Ottho Hermes VPS a déjà créé un cadre « Sécurité », propose de lui donner ce rôle (même nom de profil, ex. `securite`) plutôt qu'un doublon. Modèle : un modèle de bon raisonnement, fournisseur et identifiant vérifiés.

## Étape 2 — ses sources SSH connues

Demande d'où elle se connecte au VPS : l'adresse IP publique de sa box ou de son bureau (elle la trouve sur un site « quelle est mon IP », depuis le même réseau), éventuellement un préfixe IPv6 et l'adresse du serveur lui-même s'il se sauvegarde en SSH. Ces adresses ne sont pas des secrets, mais ce sont des données personnelles : elles restent dans `/etc/ottho-agents/securite.json` sur le serveur, jamais dans un fichier versionné.

Une adresse inconnue n'est pas une erreur : l'agent signalera simplement ses connexions comme `INCONNUE` jusqu'à ce qu'elle l'ajoute.

## Étape 3 — installer

Annonce : un profil créé ou complété, garde-fous (terminal coupé, écriture limitée à `workspace/`), un service systemd de collecte horaire en lecture seule, deux tâches planifiées. Rien n'est supprimé ; copies dans `/var/backups/ottho-agents/securite/`. Après accord :

```bash
bash .ottho-agents/securite run install --target <docker:conteneur|native:utilisateur> --owner "<Prénom>" [--provider <fournisseur> --model <identifiant>]
bash .ottho-agents/securite run set "ssh_known_sources=<ip1>,<préfixe ipv6>/64"
```

Une ligne `KO` arrête tout : explique, corrige, relance (rejouable).

## Étape 4 — le bot, saisi par la personne

`bash .ottho-agents/securite cmd secret telegram` affiche la commande ; elle la tape elle-même : un bot dédié et son identifiant Telegram numérique. Clé de modèle propre au profil si besoin : `secret model <VARIABLE>` ou `secret login <fournisseur>`.

## Étape 5 — vérifier pour de vrai

```bash
bash .ottho-agents/securite run test
```

Lis avec elle l'instantané affiché : c'est sa posture actuelle. Repère tout de suite les points rouges évidents (SSH par mot de passe, conteneur privilégié, bot ouvert à tous, fail2ban absent) et propose le skill `securite` du plugin Ottho Hermes VPS pour les corriger. Vraie preuve : elle écrit au bot « fais-moi le point sécurité » et reçoit une réponse appuyée sur l'instantané. La première veille horaire fera un bilan complet, les suivantes seront silencieuses tant que rien ne change.

## Fin

Mode d'emploi : une alerte = la lire, vérifier la preuve, appliquer la correction proposée elle-même (jamais en fermant son propre accès SSH : une deuxième session ouverte pendant tout changement SSH ou pare-feu). Nouvelle adresse de connexion : `run set ssh_known_sources=…`. Après un changement volontaire (nouveau conteneur, port ouvert), `run push` pour que l'agent voie le nouvel état.
