"""Facts dictated by the owner on Telegram, usable at once by the mail agent.

Stored in ``$HERMES_HOME/mail-agent/facts.json`` (0600). When the owner keeps a knowledge base, every fact carries
``kb: pending`` until it has been copied into a page there.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

_LOCK = threading.RLock()


class Facts:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"next_id": 1, "facts": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def all(self, include_retired: bool = False) -> list[dict]:
        with _LOCK:
            facts = self._load()["facts"]
        return [f for f in facts if include_retired or not f.get("retired")]

    def add(self, brand: str, topic: str, text: str) -> dict:
        with _LOCK:
            data = self._load()
            fact = {"id": f"F{data['next_id']}", "brand": brand, "topic": topic, "text": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M", time.localtime()), "kb": "pending"}
            data["next_id"] += 1
            data["facts"].append(fact)
            self._save(data)
            return fact

    def retire(self, fact_id: str, replaced_by: Optional[str] = None) -> Optional[dict]:
        with _LOCK:
            data = self._load()
            for fact in data["facts"]:
                if fact["id"] == fact_id and not fact.get("retired"):
                    fact["retired"] = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                    if replaced_by:
                        fact["replaced_by"] = replaced_by
                    self._save(data)
                    return fact
        return None
