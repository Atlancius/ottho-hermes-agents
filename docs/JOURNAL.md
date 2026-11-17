# Journal — Ottho Hermes Agents

## 2026-11-17 — Création des trois plugins (v1.0.0)

- Demande : « des plugins à partager sur Ottho Academy : un agent gestion de mail comme le mien, un agent update et security comme les miens. Les étudiants doivent pouvoir les installer et les déployer sur leur VPS en les configurant avec leur connexion et adaptés à leur architecture. »
- Sources : agents de production de l'auteur (dépôt privé, aucune donnée reprise) ; format et règles du plugin `ottho-hermes-vps` 1.3.0.
- Fait : dépôt `ottho-hermes-agents`, marketplace `ottho-agents`, plugins `agent-mail`, `agent-updates`, `agent-securite` (skills `installer`, `reglages` pour le mail, `statut`), kits serveur, socle `shared/`, tests, banc d'intégration. Décisions : `DECISIONS.md` (ADR-001 à 005). Erreurs : `ERREURS.md` (ERR-001 à 005). Essais : `essais/REGISTRE-ESSAIS.md` (E-001 à E-004).
- Preuves : 19/19 tests (Windows et Ubuntu WSL) ; installations réelles des trois agents sur le banc `ottho-test` (Hermes v0.22.2) ; plugin mail chargé par la vraie gateway.
- Reste : E-005 (boîte IMAP et bot d'essai réels), test d'une installation native, visuels de fiche (Codex `image_gen`), dépôt GitHub et fiches marketplace (accord de l'auteur), intégration éventuelle au parcours `ottho-hermes-vps`.
- Banc laissé en l'état : profils `essaiupdates`, `essaisecurite`, `essaimail` dans `hermes-equipes`, tâches en pause, minuteries `ottho-agent-*-collect` arrêtées, kits dans `/opt/ottho-agents/`, réglages dans `/etc/ottho-agents/`, travail dans `/root/essai-agents`.

## 2026-11-17 — Publication

- Dépôt public : https://github.com/Atlancius/ottho-hermes-agents (accord : dépôt public, étagère Formation IA Agent, visuels).
- Avant publication : liste de motifs privés sortie de Git (`tests/private-denylist.txt`, ignoré), docs assainies (aucune référence à l'infrastructure de production), gitleaks sans fuite.
- Vérifié : `claude plugin marketplace add Atlancius/ottho-hermes-agents` puis installation de `agent-securite@ottho-agents` (1.0.0, activé), puis retrait du plugin et de la marketplace sur le poste de l'auteur.
- Couvertures : E-005. Fiches marketplace créées en brouillon, à relire avant publication.
