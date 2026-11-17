#!/usr/bin/env python3
"""Script de pré-exécution du cron Hermes des agents de veille (copie identique, source : shared/kit/lib/watch.py).

Lit <profil>/inbox/snapshot.txt (écrit par l'hôte) et le compare au dernier instantané analysé.
- Rien de neuf : imprime « NO_CHANGE » ; le prompt du cron demande alors exactement [SILENT].
- Sinon : « CHANGE DETECTED », les lignes apparues et disparues, puis l'instantané complet.
- Instantané trop vieux (collecte arrêtée) : « CHANGE DETECTED » avec l'alerte, une fois par jour au plus.
Option --full : imprime l'instantané complet sans toucher à l'état (revue hebdomadaire, question de l'humain).
Option --monitor : sortie STABLE pour le mode moniteur de Hermes (`cron create --monitor-script`) : état de la collecte
puis instantané ; Hermes compare lui-même deux sorties et n'appelle le modèle que si elles diffèrent.
"""
import hashlib
import json
import os
import sys
import time

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(HOME, "inbox", "snapshot.txt")
STAMP = os.path.join(HOME, "inbox", "collected_at")
STATE = os.path.join(HOME, "workspace", ".watch-state.json")
MAX_AGE_FILE = os.path.join(HOME, "inbox", "max_age")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) if path.endswith(".json") else fh.read()
    except (OSError, ValueError):
        return default


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE)


def main():
    snap = load(SNAP, None)
    if snap is None:
        print("CHANGE DETECTED\nAucun instantané : la collecte de l'hôte n'a jamais tourné. "
              "À lancer en root : systemctl status ottho-agent-*-collect.timer")
        return
    try:
        max_age = int(str(load(MAX_AGE_FILE, "10800")).strip() or 10800)
    except ValueError:
        max_age = 10800
    try:
        age = time.time() - int(str(load(STAMP, "0")).strip() or 0)
    except ValueError:
        age = max_age + 1
    if "--full" in sys.argv or "--monitor" in sys.argv:
        stale = age > max_age
        print("## Collecte de l'hôte")
        print("ARRÊTÉE : instantané trop ancien, vérifier systemctl status ottho-agent-*-collect.timer"
              if stale else "à jour")
        print(snap)
        return
    state = load(STATE, {})
    if age > max_age:
        today = time.strftime("%Y-%m-%d")
        if state.get("stale_alert") != today:
            state["stale_alert"] = today
            save_state(state)
            print(f"CHANGE DETECTED\nL'instantané date de {int(age // 3600)} h : la collecte de l'hôte est arrêtée. "
                  "Vérification à proposer : systemctl status ottho-agent-*-collect.timer")
            return
    digest = hashlib.sha256(snap.encode("utf-8")).hexdigest()
    if digest == state.get("digest"):
        print("NO_CHANGE")
        return
    before = set((state.get("lines") or []))
    now = [line for line in snap.splitlines() if line.strip() and not line.startswith("## ")]
    added = [line for line in now if line not in before]
    removed = [line for line in before if line not in set(now)]
    first = not state.get("digest")
    state.update(digest=digest, lines=now, changed_at=time.strftime("%Y-%m-%d %H:%M"))
    save_state(state)
    print("CHANGE DETECTED")
    if first:
        print("Premier instantané analysé : fais un bilan complet (état général, écarts, priorités).")
    else:
        print("## Apparu depuis la dernière analyse")
        print("\n".join(f"+ {line}" for line in added) or "(rien)")
        print("## Disparu depuis la dernière analyse")
        print("\n".join(f"- {line}" for line in sorted(removed)) or "(rien)")
    print("\n## Instantané complet\n" + snap)


if __name__ == "__main__":
    main()
