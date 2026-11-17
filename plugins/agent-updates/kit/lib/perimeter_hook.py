#!/usr/bin/env python3
"""Hook Hermes pre_tool_call des agents Ottho « veille » (mises à jour, sécurité) : périmètre strict.

Installé dans <profil>/hooks/ottho_perimeter.py (copie identique dans chaque plugin, source :
shared/kit/lib/perimeter_hook.py).
- terminal, execute_code, process_manage : refusés. L'agent ne lance aucune commande : il lit l'instantané
  préparé par l'hôte et propose les commandes, que son humain tape lui-même.
- write_file, patch : seulement sous <profil>/workspace/.
Fail-closed : charge utile illisible = blocage. stdin : {tool_name, tool_input, cwd, ...}.
Sortie : code 2 + JSON = blocage ; code 0 = autorisé.
"""
import json
import os
import posixpath
import sys

PROFILE_HOME = posixpath.dirname(posixpath.dirname(posixpath.abspath(__file__)))
WORKSPACE = PROFILE_HOME + "/workspace/"
BLOCKED = {"terminal", "execute_code", "process_manage"}


def block(message):
    print(json.dumps({"action": "block", "message": f"[périmètre agent Ottho] {message}"}, ensure_ascii=False))
    sys.exit(2)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        block("charge utile illisible")
    tool = str(payload.get("tool_name") or "")
    args = payload.get("tool_input") or {}
    if tool in BLOCKED:
        block(f"{tool} est désactivé pour cet agent : propose la commande, ton humain la lance lui-même")
    if tool in ("write_file", "patch"):
        raw = str(args.get("path") or args.get("file_path") or "")
        if not raw:
            block("chemin absent")
        base = payload.get("cwd") or PROFILE_HOME
        real = posixpath.normpath(raw if raw.startswith("/") else posixpath.join(base, raw))
        if not (real + "/").startswith(WORKSPACE) or os.path.islink(real):
            block(f"écriture limitée à {WORKSPACE}")


if __name__ == "__main__":
    main()
