---
name: statut
description: État et dépannage de l'agent mail Hermes sans rien modifier d'abord - mode, plugin, accès IMAP et bot présents (oui/non), mails suivis, connexion testée, causes fréquentes (mot de passe refusé, aucun mail traité, bot muet, mauvais classement) et correctif proposé. Déclencheurs - où en est mon agent mail, mon agent mail ne répond plus, il classe mal, erreur IMAP.
---

# Agent mail — statut et dépannage

Règles : [regles.md](../../references/regles.md). Lanceur : `bash .ottho-agents/mail …` (absent : étape 0 du skill `installer`).

## 1. Constat (lecture seule)

```bash
bash .ottho-agents/mail run status
bash .ottho-agents/mail run test
```

Résume en 6 lignes : mode, accès présents, connexion IMAP, bot, nombre de mails suivis, ce qui manque.

## 2. Causes fréquentes

| Symptôme | Cause probable | Correctif (après accord) |
|---|---|---|
| `ÉCHEC : identifiants refusés` | mot de passe changé, mot de passe d'application requis, IMAP désactivé | la personne relance `secret imap` elle-même |
| `imap.host absent` | réglage incomplet | `config get`, corriger `imap.host`, `config put` |
| aucun mail traité, IMAP OK | gateway arrêtée, plateforme `mail_inbox` non chargée, plugin non activé | `logs`, puis `restart` ; si le plugin n'est pas chargé, relancer `install` (rejouable, rien n'est effacé) |
| bot muet | jeton révoqué, identifiant Telegram faux, gateway arrêtée | `secret telegram` à refaire par la personne, puis `test` |
| `ConnectionRefused` / délai | proxy de sortie ou pare-feu qui bloque le port 993 | autoriser le serveur IMAP dans la liste blanche de la cellule |
| mauvais classement | description de catégorie floue, dossier mal nommé | skill `reglages`, puis corrections par référence sur Telegram |
| brouillon inventé (prix, délai) | fait absent de la base | dicter le fait au bot ou l'ajouter à la base ; le brouillon doit porter `[À COMPLÉTER]` |
| mail suspect non signalé | — | le signaler sur Telegram (« M1234 suspect ») et relire la section Sécurité du SOUL |

Journal de la cible : `bash .ottho-agents/mail run logs 150` (adresses mail et jetons masqués). Cherche les lignes `mail-agent`, `mail_inbox`, `ERROR`. Ne recopie dans ta réponse que l'erreur utile, jamais le contenu d'un mail.

## 3. Après correctif

Relance `test`, puis un vrai mail de test. Dis ce qui a été fait, la preuve, ce qui reste.
