---
name: statut
description: État et dépannage de l'agent sécurité Hermes - collecte horaire, âge de l'instantané, tâches Telegram, bot, sources SSH connues, journal masqué, causes fréquentes (fausses alertes, agent muet, collecte arrêtée) et correctif proposé. Déclencheurs - où en est mon agent sécurité, trop d'alertes, il ne m'écrit plus, ajouter une IP connue.
---

# Agent sécurité — statut et dépannage

Règles : [regles.md](../../references/regles.md). Lanceur : `bash .ottho-agents/securite …` (absent : étape 0 du skill `installer`).

## 1. Constat (lecture seule)

```bash
bash .ottho-agents/securite run status
bash .ottho-agents/securite run test
```

Résume en 6 lignes : collecte active, âge de l'instantané, tâches, bot, sources SSH connues réglées ou non, ce qui manque.

## 2. Causes fréquentes

| Symptôme | Cause probable | Correctif (après accord) |
|---|---|---|
| alerte à chaque connexion SSH | sa propre adresse n'est pas dans les sources connues, ou elle a changé | `run set ssh_known_sources=…` avec la nouvelle adresse |
| alerte « empreinte nftables » répétée | règles réécrites par Docker ou un outil qui ajoute des compteurs | regarder ce qui change ; si c'est attendu (redémarrage de conteneur), l'agent répond `[SILENT]` ; sinon, à investiguer |
| aucun message depuis des jours | normal si rien n'a changé ; sinon gateway arrêtée | lui faire écrire au bot ; `run logs`, puis `run restart` |
| « collecte de l'hôte arrêtée » | service systemd en échec | `systemctl status ottho-agent-securite-collect.timer` (lecture), puis relancer `install` (rejouable) |
| tâche absente de `cron list` | version de Hermes sans `cron create --script` | mettre Hermes à jour (agent mises à jour) ou recréer la tâche à la main avec la personne |
| section « Garde-fous des agents » vide | installation native ou conteneur sans Python de Hermes | contrôle à faire à la main (`approvals.mode` des profils) |

Journal : `bash .ottho-agents/securite run logs 150` (adresses et jetons masqués). Ne recopie que l'erreur utile.

## 3. Une alerte critique

Ne panique pas, ne coupe rien à l'aveugle. Lis la preuve dans l'instantané (`run test`), recoupe avec une deuxième source (ex. `last -a`, `docker ps`, `ss -tlnp` lancés par elle), puis applique la première action proposée par l'agent. Accès inconnu confirmé : changer les mots de passe et clés concernés depuis un autre appareil, révoquer les jetons des bots, puis le skill `securite` d'Ottho Hermes VPS. Dis ce qui a été fait, la preuve, ce qui reste.
