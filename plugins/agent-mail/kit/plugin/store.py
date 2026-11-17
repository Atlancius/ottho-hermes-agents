"""Local state of the mail agent under ``$HERMES_HOME/mail-agent/``: IMAP watermark and one JSON record per mail.

Records hold mail content (personal data): files are 0600, never leave the cell, pruned after retention.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

REF_RE = re.compile(r"^M\d{1,12}$")
_LOCK = threading.RLock()


def valid_ref(ref: str) -> bool:
    return bool(REF_RE.match(ref or ""))


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.records = root / "records"
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    @staticmethod
    def _read(path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return None

    # -- watermark ---------------------------------------------------------------------------------
    def state(self) -> dict:
        with _LOCK:
            return self._read(self.root / "state.json") or {}

    def save_state(self, **fields: Any) -> dict:
        with _LOCK:
            data = self.state()
            data.update(fields, updated_at=time.time())
            self._write(self.root / "state.json", data)
            return data

    # -- records -----------------------------------------------------------------------------------
    def _path(self, ref: str) -> Path:
        if not valid_ref(ref):
            raise ValueError(f"référence invalide : {ref!r}")
        return self.records / f"{ref}.json"

    def get(self, ref: str) -> Optional[dict]:
        with _LOCK:
            return self._read(self._path(ref))

    def put(self, record: dict) -> dict:
        with _LOCK:
            record["updated_at"] = time.time()
            self._write(self._path(record["ref"]), record)
            return record

    def update(self, ref: str, **fields: Any) -> dict:
        with _LOCK:
            record = self.get(ref)
            if record is None:
                raise KeyError(ref)
            record.update(fields)
            return self.put(record)

    def all(self) -> Iterator[dict]:
        with _LOCK:
            paths = sorted(self.records.glob("M*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths:
            record = self._read(path)
            if record:
                yield record

    def find_by_message_id(self, message_id: str) -> Optional[dict]:
        """Record already tracking this Message-ID (a mail moved back into INBOX gets a new UID, not a new identity)."""
        if not message_id:
            return None
        return next((rec for rec in self.all() if rec.get("message_id") == message_id), None)

    def prune(self, retention_days: float) -> int:
        cutoff = time.time() - retention_days * 86400
        removed = 0
        with _LOCK:
            for path in self.records.glob("M*.json"):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
        return removed
