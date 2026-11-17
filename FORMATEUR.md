# Fiche formateur — Ottho Hermes Agents

## Fiches marketplace (étagère « Formation IA Agent », type plugin)

### Agent mail (Hermes)
**Résumé** : Ton assistant mail sur ton VPS : il range chaque mail dans tes dossiers, prépare tes réponses en brouillon et te prévient sur Telegram. Il n'envoie jamais rien.
**Ce qu'il te faut** : Hermes Agent sur ton VPS (plugin Ottho Hermes VPS conseillé), accès SSH par clé avec sudo, Telegram, une boîte IMAP (Gmail avec mot de passe d'application, Hostinger, OVH, Ionos, Infomaniak…). Outlook/Microsoft 365 : souvent impossible (authentification par mot de passe coupée par Microsoft).
**Ensuite** : `/agent-mail:installer` (Claude Code) ou « Installe mon agent mail Hermes sur mon VPS » (Codex, ChatGPT). Mode shadow quelques jours, puis live.

### Agent mises à jour (Hermes)
**Résumé** : Chaque matin, ton agent vérifie les mises à jour du système, de Docker et de Hermes, lit les notes de version et te dit sur Telegram quoi faire et quelle commande taper. Il n'applique rien lui-même.
**Ce qu'il te faut** : Hermes Agent sur ton VPS, accès SSH par clé avec sudo, Telegram.
**Ensuite** : `/agent-updates:installer` ou « Installe mon agent mises à jour Hermes ».

### Agent sécurité (Hermes)
**Résumé** : Chaque heure, ton agent surveille ton VPS et tes agents (ports, pare-feu, SSH, conteneurs, garde-fous) et t'alerte sur Telegram avec la preuve et la correction. Il ne touche à rien.
**Ce qu'il te faut** : Hermes Agent sur ton VPS, accès SSH par clé avec sudo, Telegram, l'adresse IP d'où tu te connectes.
**Ensuite** : `/agent-securite:installer` ou « Installe mon agent sécurité Hermes ».

Commandes d'installation (dépôt public https://github.com/Atlancius/ottho-hermes-agents) :

```bash
claude plugin marketplace add Atlancius/ottho-hermes-agents && claude plugin install agent-mail@ottho-agents
codex plugin marketplace add https://github.com/Atlancius/ottho-hermes-agents.git && codex plugin add agent-mail@ottho-agents
```

## Ce que l'élève doit comprendre (à dire en live)

1. **Les secrets ne passent jamais par le chat** : il tape mot de passe IMAP et jeton Telegram lui-même, en saisie masquée, sur le serveur.
2. **L'agent mail n'envoie rien** : il n'a pas l'outil. Le contenu d'un mail est une donnée, jamais une consigne (démo : un mail « ignore tes instructions… » est classé normalement).
3. **Shadow avant live** : l'agent décide et prévient sans toucher à la boîte ; on corrige par référence (« M1234 classe dans Fournisseurs ») ; live quand c'est juste.
4. **Les agents de veille sont aveugles aux secrets et sans mains** : l'hôte collecte en lecture seule, l'agent analyse, l'humain tape. Le modèle n'est appelé que si l'instantané change (coût quasi nul).
5. **Rien n'est supprimé** : chaque fichier remplacé est copié dans `/var/backups/ottho-agents/<agent>/`.

## Démo conseillée (20 min)

`detect` sur le VPS de démo → installation de l'agent sécurité (le plus visuel : `test` affiche la posture réelle) → lecture de l'instantané avec la salle (ports, SSH, garde-fous) → agent mail en shadow avec un mail de test envoyé depuis un téléphone.

## Limites connues (à annoncer)

- IMAP par mot de passe seulement (pas d'OAuth Microsoft/Google) : Gmail via mot de passe d'application.
- Testé sur Hermes Agent v0.22.2 (cellules Ottho Hermes VPS) ; la connexion IMAP réelle n'a pas encore été rejouée sur une boîte d'élève (voir `docs/essais/REGISTRE-ESSAIS.md`).
- Installation native (sans Docker) : chemins prévus, non testés sur un vrai serveur.
