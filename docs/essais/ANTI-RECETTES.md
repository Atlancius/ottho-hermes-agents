# Anti-recettes — Ottho Hermes Agents

## A-001 — Chemin absolu dans `cron create --script` (E-002)
- **Cause** : Hermes v0.22.2 n'accepte qu'un nom de fichier relatif à `<profil>/scripts/`.
- **Signe d'alerte** : `Script path must be relative to …`.
- **Alternative** : R-001.

## A-002 — Éditer des scripts avec `Path.write_text` sous Windows (ERR-001)
- **Cause** : traduction `\n` → `\r\n`, bash casse sur le VPS.
- **Signe d'alerte** : `$'\r'` dans une erreur bash.
- **Alternative** : `write_bytes`, ou l'outil d'édition ; test `test_unix_line_endings`.

## A-003 — Insérer `"\n"` via un heredoc Python dans un fichier Python (E-002)
- **Cause** : l'échappement est interprété par le script d'édition, un vrai saut de ligne coupe la chaîne.
- **Alternative** : outil d'édition direct, ou `print()` sur deux lignes.

## A-004 — Monitor-script qui garde un état (E-002)
- **Cause** : une sortie qui alterne CHANGE/NO_CHANGE change d'empreinte à chaque passage et réveille le modèle pour rien.
- **Alternative** : `watch.py --monitor` imprime seulement l'instantané et l'état de la collecte ; le diff est fait par Hermes.
