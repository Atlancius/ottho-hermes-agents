# Recettes — Ottho Hermes Agents

## R-001 — Tâche de veille Hermes sans coût quand rien ne change (E-002)
1. Script stable (aucun horodatage, aucun compteur) dans `<profil>/scripts/monitor.py`.
2. `hermes -p <profil> cron create "<expr>" "<prompt>" --name <nom> --monitor-script monitor.py --deliver telegram` (nom de fichier seul).
3. Prompt : « S'il dit NO_CHANGE ou que rien d'utile n'a changé : réponds exactement [SILENT]. »
4. Vérifier : `cron list` affiche `Monitor: monitor.py (agent runs only on output change)` ; deux exécutions du script = même empreinte.

## R-002 — Banc d'essai réel d'un plugin d'agent (E-002 à E-004)
1. Distro WSL `ottho-test` (kit Ottho Hermes VPS, cellules `hermes-direction` / `hermes-equipes`, systemd).
2. `MSYS_NO_PATHCONV=1 wsl.exe -d ottho-test -u root -- bash <dépôt>/tests/integration/wsl_run.sh <dépôt> <agent> run install …` (chemin `/mnt/c/…` construit à la main : `wslpath` mange les antislash depuis Git Bash).
3. Profils d'essai préfixés `essai…` ; `check_profile.sh` pour la config et le hook ; `plugin_load.py` pour un plugin.
4. Fin d'essai : `pause_bench.sh <conteneur> <profils…>` (tâches en pause, minuteries arrêtées, rien supprimé).

## R-003 — Couverture marketplace Ottho d'un plugin (E-005)
1. Références : couvertures existantes de la marketplace (Ottho Hermes VPS, Ottho Brain).
2. Prompt anglais : « Landscape 16:9 cover illustration, same art direction as the reference images: soft glossy 3D clay style, rounded shapes, pastel palette of lavender (#A78BFA), sky blue (#93C5FD), mint green (#86EFAC) and butter yellow (#FDE68A) on warm cream, light wooden table…, blurred bright window and green potted plants…, soft daylight » + sujet + « Absolutely no text, no letters, no numbers, no logos, no watermark. »
3. `codex exec` + `image_gen`, un job par image, `< /dev/null`, chemin lu dans `IMAGE_PATH`.
4. Contrôle visuel, puis `assets/cover.png` du plugin et envoi sur la fiche (`get_marketplace_image_upload_url`).
