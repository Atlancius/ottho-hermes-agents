---
name: statut
description: État et dépannage de l'agent mises à jour Hermes - collecte planifiée, âge de l'instantané, tâches Telegram, bot, journal masqué, causes fréquentes (agent muet, collecte arrêtée, tâche absente) et correctif proposé. Déclencheurs - où en est mon agent mises à jour, il ne m'écrit plus, la collecte ne tourne pas.
---

# Agent mises à jour — statut et dépannage

Règles : [regles.md](../../references/regles.md). Lanceur : `bash .ottho-agents/updates …` (absent : étape 0 du skill `installer`).

## 1. Constat (lecture seule)

```bash
bash .ottho-agents/updates run status
bash .ottho-agents/updates run test
```

Résume en 6 lignes : collecte active et prochaine heure, âge de l'instantané, tâches planifiées, bot, ce qui manque.

## 2. Causes fréquentes

| Symptôme | Cause probable | Correctif (après accord) |
|---|---|---|
| aucun message depuis des jours | normal si rien n'a changé (réponse `[SILENT]`) ; sinon gateway arrêtée | lui faire écrire au bot ; `run logs`, puis `run restart` |
| « collecte de l'hôte arrêtée » | service systemd désactivé ou en échec | `systemctl status ottho-agent-updates-collect.timer` (lecture), puis relancer `install` (rejouable) |
| tâche absente de `cron list` | version de Hermes sans `cron create --script`, ou nom changé | `hermes … cron create --help` dans la cible ; mettre Hermes à jour (proposition de l'agent lui-même) ou recréer la tâche à la main avec la personne |
| « dernière publication Hermes : inconnue » | pas d'accès sortant vers api.github.com depuis l'hôte, ou limite d'appels | sans gravité ; vérifier la sortie Internet de l'hôte |
| `apt` absent | système non Debian/Ubuntu | collecte système limitée ; Docker et Hermes restent suivis |

Journal : `bash .ottho-agents/updates run logs 150` (adresses et jetons masqués). Ne recopie que l'erreur utile.

## 3. Après correctif

`run push` puis `run test`, et un message au bot. Dis ce qui a été fait, la preuve, ce qui reste.
