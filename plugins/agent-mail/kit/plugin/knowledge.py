"""Read-only knowledge for mail replies: a bounded, allowlisted slice of a Markdown folder (Obsidian vault…).

Only business pages useful to answer clients, suppliers and partners are indexed; internal areas (finance,
strategy, brand assets, history, watch) and retired pages are never exposed. Nothing here writes anywhere.
"""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_WORD_RE = re.compile(r"[a-z0-9]{2,}")
_STOP = set("""le la les un une des de du d l et ou en au aux a pour par sur dans avec sans ce ces cet cette qui que quoi
dont est sont etre ete je tu il elle nous vous ils elles mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs
pas plus ne se si y on the and of to in for is are be it this that with as at by from""".split())
_RESCAN_SECONDS = 300


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(_fold(text)) if w not in _STOP]


def _field(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*(.*)$", frontmatter, re.M)
    return match.group(1).strip().strip("\"'") if match else ""


@dataclass
class Page:
    path: str            # relative to the knowledge root, forward slashes
    title: str
    tldr: str
    tags: str
    body: str
    mtime: float
    tf: Counter = field(default_factory=Counter)
    length: int = 0


@dataclass
class Scope:
    root: Path
    include: tuple[str, ...]
    exclude_dirs: frozenset[str]
    exclude_status: frozenset[str]

    def allows(self, rel: str) -> bool:
        parts = rel.split("/")
        if parts[-1].startswith("--") or not rel.endswith(".md"):
            return False
        if self.include and not any(rel == inc or rel.startswith(inc.rstrip("/") + "/") for inc in self.include):
            return False
        return not any(p in self.exclude_dirs for p in parts[:-1])


class Knowledge:
    def __init__(self, scope: Scope):
        self.scope = scope
        self.pages: dict[str, Page] = {}
        self.df: Counter = Counter()
        self.avg_len = 1.0
        self._scanned_at = 0.0
        self._lock = threading.Lock()

    def _load(self, file: Path, rel: str) -> Optional[Page]:
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        match = _FRONTMATTER_RE.match(text)
        frontmatter, body = (match.group(1), text[match.end():]) if match else ("", text)
        status = _field(frontmatter, "status").lower()
        if _field(frontmatter, "retrieval").lower() == "excluded" or status in self.scope.exclude_status:
            return None
        # A page marked private (private: true / prive: true) never reaches the agent.
        if _field(frontmatter, "private").lower() in ("true", "oui", "yes") or                 _field(frontmatter, "prive").lower() in ("true", "oui", "yes"):
            return None
        title = _field(frontmatter, "title") or file.stem
        page = Page(path=rel, title=title, tldr=_field(frontmatter, "tldr"), tags=_field(frontmatter, "tags"),
                    body=body.strip(), mtime=file.stat().st_mtime)
        # Title, tldr and tags weigh more than the body.
        weighted = tokens(title) * 3 + tokens(page.tldr) * 2 + tokens(page.tags) * 2 + tokens(body)
        page.tf, page.length = Counter(weighted), max(1, len(weighted))
        return page

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and time.monotonic() - self._scanned_at < _RESCAN_SECONDS and self.pages:
                return
            root = self.scope.root
            pages: dict[str, Page] = {}
            for include in (self.scope.include or ("",)):
                base = root / include if include else root
                if not base.is_dir():
                    continue
                for file in base.rglob("*.md"):
                    rel = file.relative_to(root).as_posix()
                    if not self.scope.allows(rel):
                        continue
                    old = self.pages.get(rel)
                    try:
                        mtime = file.stat().st_mtime
                    except OSError:
                        continue
                    page = old if old is not None and old.mtime == mtime else self._load(file, rel)
                    if page is not None:
                        pages[rel] = page
            df: Counter = Counter()
            for page in pages.values():
                df.update(page.tf.keys())
            self.pages, self.df = pages, df
            self.avg_len = sum(p.length for p in pages.values()) / max(1, len(pages))
            self._scanned_at = time.monotonic()

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.refresh()
        terms = list(dict.fromkeys(tokens(query)))
        if not terms:
            return []
        n, k1, b = max(1, len(self.pages)), 1.4, 0.75
        scored = []
        for page in self.pages.values():
            score = 0.0
            for term in terms:
                freq = page.tf.get(term)
                if not freq:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * page.length / self.avg_len))
            if score > 0:
                scored.append((score, page))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"path": p.path, "title": p.title, "tldr": p.tldr[:400], "score": round(s, 2),
                 "extrait": _snippet(p.body, terms)} for s, p in scored[:limit]]

    def read(self, rel: str, max_chars: int) -> Optional[dict]:
        self.refresh()
        rel = rel.strip().lstrip("/").replace("\\", "/")
        page = self.pages.get(rel)
        if page is None:
            return None
        return {"path": page.path, "title": page.title, "tldr": page.tldr,
                "contenu": page.body[:max_chars] + ("\n[… tronqué]" if len(page.body) > max_chars else "")}


def search_facts(facts: list[dict], query: str, limit: int = 5) -> list[dict]:
    """Facts dictated by the owner: few and authoritative, so a plain term-overlap score is enough."""
    terms = set(tokens(query))
    scored = []
    for fact in facts:
        topic, text = set(tokens(fact.get("topic", ""))), set(tokens(fact.get("text", "")))
        score = sum(3 if t in topic else 1 for t in terms if t in topic or t in text)
        if score:
            scored.append((score, fact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{"path": f"owner/{f['id']}", "marque": f["brand"], "sujet": f["topic"], "fait": f["text"],
             "date": f["created_at"]} for _, f in scored[:limit]]


def _snippet(body: str, terms: list[str], width: int = 280) -> str:
    folded = _fold(body)
    positions = [folded.find(t) for t in terms if folded.find(t) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    return re.sub(r"\s+", " ", body[start:start + width]).strip()


_instance: Optional[Knowledge] = None
_instance_key: Optional[tuple] = None


def get(config: dict) -> Knowledge:
    global _instance, _instance_key
    cfg = config.get("knowledge") or {}
    scope = Scope(root=Path(cfg.get("root") or "/nonexistent-knowledge"), include=tuple(cfg.get("include") or ()),
                  exclude_dirs=frozenset(cfg.get("exclude_dirs") or ()),
                  exclude_status=frozenset(s.lower() for s in (cfg.get("exclude_status") or ())))
    key = (scope.root, scope.include, scope.exclude_dirs, scope.exclude_status)
    if _instance is None or _instance_key != key:
        _instance, _instance_key = Knowledge(scope), key
    return _instance
