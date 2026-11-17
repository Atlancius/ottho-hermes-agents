# Registre des essais — Ottho Hermes Agents

Append-only : la plus récente en haut. On ne supprime jamais une fiche ratée.

| ID | Date | Sortie | Verdict | Une ligne |
|---|---|---|---|---|
| E-004 | 2026-11-17 | banc `ottho-test`, profil `essaimail` | ⚠️ partiel | plugin chargé par la vraie gateway ; IMAP réel non testé (aucune boîte d'essai) |
| E-003 | 2026-11-17 | banc `ottho-test`, profil `essaisecurite` | ✅ retenu | installation réelle, instantané de posture complet, garde-fous de tous les profils lus |
| E-002 | 2026-11-17 | banc `ottho-test`, profil `essaiupdates` | ✅ retenu (après correctifs) | installation réelle, hook et moniteur vérifiés dans la cellule |
| E-001 | 2026-11-17 | `tests/test_kits.py` | ✅ retenu | 19 tests hors ligne, Windows et Ubuntu WSL |

---

## E-004 — Agent mail sur Hermes réel (2026-11-17)
- **Sortie** : profil `essaimail` dans `hermes-equipes` (distro WSL `ottho-test`, kit Ottho Hermes VPS 1.0.0, Hermes v0.22.2).
- **Intention** : prouver que le plugin dérivé de l'agent de production (écrit pour v0.22.7) se charge sur la version des élèves.
- **Recette** : `bash tests/integration/wsl_run.sh <dépôt> mail run install --target docker:hermes-equipes --profile essaimail --owner Camille --imap-host imap.example.com` ; `tests/integration/plugin_load.py` dans la cellule ; `run restart` ; `run logs 400`.
- **Résultat** : `API Hermes manquante : aucune`, 20 outils et la plateforme `mail_inbox` enregistrés ; au démarrage, `✗ mail_inbox failed to connect (profile: essaimail)` (attendu : aucun accès IMAP saisi), les autres bots de la cellule continuent.
- **Ce qui n'allait pas** : connexion IMAP, IDLE, tri, brouillon et notification Telegram **non rejoués** : il faut une boîte et un bot d'essai.
- **Verdict** : ⚠️ partiel. **Suite** : E-005 avec une boîte d'essai (Hostinger ou Gmail mot de passe d'application) et un bot d'essai, en shadow puis live.

## E-003 — Agent sécurité sur Hermes réel (2026-11-17)
- **Recette** : `wsl_run.sh … securite run install --target docker:hermes-equipes --profile essaisecurite --owner Camille`, `run set ssh_known_sources=203.0.113.7,2001:db8:1::/48`, `run test`.
- **Résultat** : deux tâches créées (`veille-securite` en monitor-script, `revue-securite-lundi` en script), instantané : 5 conteneurs (Traefik signalé réseau hôte + socket Docker, attendu pour Traefik), ports 22/80/443, ufw actif, fail2ban `sshd`, SSH par clé, garde-fous `smart/deny` de 8 profils.
- **Ce qui n'allait pas** : disques Windows (`/mnt/c`) signalés presque pleins → `df -x 9p -x drvfs`.
- **Après l'essai** : tâches mises en pause et minuteries arrêtées (`tests/integration/pause_bench.sh`), profils conservés.

## E-002 — Agent mises à jour sur Hermes réel (2026-11-17)
- **Recette** : `tests/integration/wsl_updates.sh`, puis `run install --target docker:hermes-equipes --profile essaiupdates --owner Camille`, `run test`, `run status`, `tests/integration/check_profile.sh hermes-equipes essaiupdates`.
- **Première passe** : ❌ `cron create` refusé (ERR-004) ; ❌ `watch.py --monitor` en erreur de syntaxe (chaîne coupée par un `\n` réel inséré par un script d'édition).
- **Après correctifs** : ✅ tâches `etat-mises-a-jour` (monitor-script) et `bilan-mises-a-jour-lundi` (script) ; config : `approvals smart deny deny`, 41 motifs deny, hook fail-closed + allowlist ; hook : terminal → 2, écriture `workspace/` → 0, écriture `config.yaml` → 2, lecture → 0 ; `monitor.py` stable sur deux exécutions ; modèle hérité de la cellule.
- **Ce qui n'allait pas** : 89 mises à jour de sécurité sur le banc → listes bornées à 40/25 lignes avec total.

## E-001 — Tests hors ligne (2026-11-17)
- **Recette** : `python -m unittest discover -s tests` (Windows, Python 3.14) et sous Ubuntu WSL (Python 3.12).
- **Couverture** : synchronisation `shared/`, manifestes, frontmatter des skills et liens, syntaxe bash, compilation Python, fins de ligne, absence de données personnelles (noms, IP, adresses), hook de périmètre, cycle `watch.py` (premier instantané, NO_CHANGE, écart, alerte de collecte arrêtée une fois par jour), fusion `profile_apply.py`, rendu YAML sûr, plugin mail (marques dynamiques, procédure, mail hostile encadré, brouillon `X-Mail-Agent-Ref`, base de connaissances avec exclusions, notification, validation des réglages).
- **Résultat** : 19/19 sous Linux (2 tests POSIX sautés sous Windows).
