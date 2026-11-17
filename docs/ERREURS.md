# Registre des erreurs — Ottho Hermes Agents

## ERR-001 — Scripts en CRLF, bash cassé sur Linux (2026-11-17)
- **Symptôme** : `syntax error near unexpected token $'{\r'` sur `agent.sh` (tests sous WSL).
- **Cause racine** : fichiers modifiés par `pathlib.Path.write_text` sous Windows, qui traduit `\n` en `\r\n`.
- **Correctif** : conversion en LF, `.gitattributes` (`* text=auto eol=lf`), test `test_unix_line_endings`.
- **Preuve** : 19/19 tests sous Ubuntu WSL.
- **Du premier coup** : sous Windows, écrire en binaire (`write_bytes`) ou avec `newline="\n"`.

## ERR-002 — `agent.sh` introuvable depuis un chemin relatif (2026-11-17)
- **Symptôme** : `./lib/common.sh: No such file or directory`.
- **Cause racine** : `cd /` exécuté avant `readlink -f "$0"`.
- **Correctif** : sourcer `common.sh` puis `cd /`.
- **Preuve** : `bash plugins/agent-mail/kit/agent.sh version` OK sous WSL.

## ERR-003 — Réglages YAML cassés par une valeur (2026-11-17)
- **Symptôme** : `ScannerError` au chargement de `mail-agent.yaml` (chemin avec antislash, prénom avec apostrophe).
- **Cause racine** : valeurs insérées brutes entre guillemets dans le gabarit.
- **Correctif** : `render.py --yaml` écrit chaque valeur en chaîne JSON (valide en YAML) ; test avec `Jo D'Arc: "x" #1` et `C:\a\b`.

## ERR-004 — `hermes cron create --script` refuse un chemin absolu (2026-11-17)
- **Symptôme** : `Script path must be relative to /opt/data/profiles/<profil>/scripts/` (Hermes v0.22.2, banc réel).
- **Cause racine** : la doc publique montre `~/.hermes/scripts/…` ; Hermes exige le nom de fichier seul.
- **Correctif** : `--script review.py` / `--monitor-script monitor.py`.
- **Preuve** : `cron list` sur le banc montre `Monitor: monitor.py (agent runs only on output change)` et `Script: review.py`.

## ERR-005 — Nom de profil avec tiret accepté par le kit (2026-11-17)
- **Cause racine** : règle du kit plus large que la contrainte Hermes (minuscules et chiffres).
- **Correctif** : `valid_profile` = `^[a-z0-9]{1,31}$`, skills alignés.
