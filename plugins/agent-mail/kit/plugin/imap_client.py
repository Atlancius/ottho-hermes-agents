"""IMAP access for the mail agent.

The cell has no direct egress: TLS runs inside an HTTP CONNECT tunnel through the egress proxy.
Only IMAP is used (read, move, flag, append drafts). There is no SMTP code path: this agent cannot send mail.
"""

from __future__ import annotations

import contextlib
import imaplib
import re
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from . import imap_utf7

imaplib.Commands.setdefault("MOVE", ("SELECTED",))
imaplib.Commands.setdefault("IDLE", ("AUTH", "SELECTED"))

_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\) (?P<delim>NIL|"(?:[^"\\]|\\.)*") (?P<name>.+)$')
_APPENDUID_RE = re.compile(rb"APPENDUID \d+ (\d+)")
_EXISTS_RE = re.compile(rb"^\* \d+ (EXISTS|RECENT)")


class ImapError(Exception):
    pass


class AuthError(ImapError):
    pass


@dataclass(frozen=True)
class ImapSettings:
    host: str
    port: int
    address: str
    password: str
    proxy: str = ""
    timeout: float = 30.0


@dataclass(frozen=True)
class Folder:
    raw: str        # modified UTF-7, as sent on the wire
    name: str       # decoded display name
    delimiter: str
    flags: frozenset


def open_tunnel(proxy_url: str, host: str, port: int, timeout: float) -> socket.socket:
    proxy = urlsplit(proxy_url)
    sock = socket.create_connection((proxy.hostname, proxy.port or 3128), timeout=timeout)
    try:
        sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("egress proxy closed the connection during CONNECT")
            response += chunk
            if len(response) > 16384:
                raise OSError("oversized egress proxy response")
        status = response.split(b"\r\n", 1)[0].decode("latin-1")
        if not re.match(r"HTTP/1\.[01] 200", status):
            raise OSError(f"egress proxy refused CONNECT {host}:{port}: {status}")
        return sock
    except BaseException:
        sock.close()
        raise


class _ProxiedIMAP4_SSL(imaplib.IMAP4_SSL):
    def __init__(self, host: str, port: int, *, proxy: str, ssl_context: ssl.SSLContext, timeout: float):
        self._proxy = proxy
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        if not self._proxy:
            return super()._create_socket(timeout)
        sock = open_tunnel(self._proxy, self.host, self.port, timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def quote(mailbox_raw: str) -> str:
    return '"' + mailbox_raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ok(typ: str, data, what: str):
    if typ != "OK":
        detail = b" ".join(d if isinstance(d, bytes) else b"" for d in (data or [])).decode("utf-8", "replace")
        raise ImapError(f"{what} failed: {typ} {detail}".strip())
    return data


class Mailbox:
    """One authenticated IMAP connection. Not thread-safe: one owner thread at a time."""

    def __init__(self, settings: ImapSettings):
        self.settings = settings
        self.imap: Optional[_ProxiedIMAP4_SSL] = None
        self.caps: set[str] = set()
        self.selected: Optional[str] = None

    def __enter__(self) -> "Mailbox":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        s = self.settings
        try:
            self.imap = _ProxiedIMAP4_SSL(s.host, s.port, proxy=s.proxy, ssl_context=ssl.create_default_context(),
                                          timeout=s.timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise ImapError(f"connexion IMAP {s.host}:{s.port} impossible : {exc}") from exc
        try:
            self.imap.login(s.address, s.password)
        except imaplib.IMAP4.error as exc:
            self.close()
            text = str(exc)
            if "AUTHENTICATIONFAILED" in text.upper() or "authentication failed" in text.lower():
                raise AuthError(f"identifiants IMAP refusés pour {s.address}") from None
            raise ImapError(f"login IMAP refusé : {text}") from None
        typ, data = self.imap.capability()
        if typ == "OK" and data and data[0]:
            self.caps = set(data[0].decode("ascii", "replace").upper().split())

    def close(self) -> None:
        imap, self.imap, self.selected = self.imap, None, None
        if imap is None:
            return
        try:
            imap.logout()
        except Exception:
            with contextlib.suppress(Exception):
                imap.shutdown()

    def abort(self) -> None:
        """Unblock a thread stuck in IDLE from another thread (teardown only)."""
        imap = self.imap
        if imap is not None:
            with contextlib.suppress(Exception):
                imap.socket().shutdown(socket.SHUT_RDWR)

    # -- folders ----------------------------------------------------------------------------------
    def list_folders(self) -> list[Folder]:
        typ, data = self.imap.list()
        folders = []
        for item in _ok(typ, data, "LIST"):
            if isinstance(item, tuple):  # literal mailbox name
                line, name = item[0], item[1]
                match = _LIST_RE.match(line.rsplit(b" ", 1)[0] + b" x")
            else:
                line, name = item, None
                match = _LIST_RE.match(item or b"")
            if not match:
                continue
            if name is None:
                name = match.group("name").strip()
                if name.startswith(b'"') and name.endswith(b'"'):
                    name = name[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
            raw = name.decode("utf-8", "replace")
            delim = match.group("delim").decode()
            flags = frozenset(f.lower() for f in match.group("flags").decode().split())
            folders.append(Folder(raw=raw, name=imap_utf7.decode(raw), delimiter="" if delim == "NIL" else delim.strip('"'),
                                  flags=flags))
        return folders

    @staticmethod
    def _with_delimiter(name: str, delim: str) -> str:
        """Accept ``/`` or ``\\`` as a path separator and rewrite it to the server's own.

        Names reach this point already encoded in modified UTF-7 (ASCII, with ``,`` inside escaped runs),
        so replacing separators cannot corrupt the encoding."""
        if not delim:
            return name
        for sep in ("/", "\\"):
            if sep != delim:
                name = name.replace(sep, delim)
        return name

    def resolve_folder(self, display_name: str, folders: Optional[list[Folder]] = None) -> Optional[Folder]:
        """Match a name against the server list: full name, short name, whichever separator was typed."""
        folders = folders if folders is not None else self.list_folders()
        for folder in folders:
            wanted = self._with_delimiter(display_name.strip(), folder.delimiter).casefold()
            short = folder.name.split(folder.delimiter, 1)[1] if (folder.delimiter and folder.name.upper().startswith(
                "INBOX" + folder.delimiter)) else folder.name
            if wanted in {folder.name.casefold(), short.casefold()}:
                return folder
        return None

    def drafts_folder(self, configured: str = "") -> Folder:
        folders = self.list_folders()
        if configured:
            found = self.resolve_folder(configured, folders)
            if found:
                return found
            raise ImapError(f"dossier brouillons « {configured} » introuvable")
        for folder in folders:
            if "\\drafts" in folder.flags:
                return folder
        for candidate in ("Drafts", "Brouillons", "INBOX.Drafts", "INBOX/Drafts"):
            found = self.resolve_folder(candidate, folders)
            if found:
                return found
        raise ImapError("aucun dossier brouillons trouvé sur le serveur")

    def folder_status(self, mailbox_raw: str) -> dict:
        """Counts for a mailbox WITHOUT selecting it (IMAP STATUS): messages, unseen, uidnext."""
        typ, data = self.imap.status(quote(mailbox_raw), "(MESSAGES UNSEEN UIDNEXT)")
        blob = b" ".join(d for d in _ok(typ, data, f"STATUS {mailbox_raw}") if isinstance(d, bytes))
        counts: dict = {}
        for field in ("MESSAGES", "UNSEEN", "UIDNEXT"):
            match = re.search(field.encode("ascii") + rb"\s+(\d+)", blob)
            if match:
                counts[field.lower()] = int(match.group(1))
        return counts

    def _namespace_prefix(self, known: list[Folder], delim: str) -> str:
        """``INBOX.<delim>`` when the server keeps every folder inside the INBOX namespace.

        Dovecot answers a bare CREATE with "should probably be prefixed with: INBOX." — the layout is the
        server's, so it gets read from the existing folders rather than assumed."""
        if not delim:
            return ""
        for folder in known:
            if folder.raw.upper().startswith("INBOX" + delim):
                return "INBOX" + delim
        return ""

    def _create_tree(self, base: str, known: list[Folder], delim: str) -> list[str]:
        existing = {f.raw for f in known}
        segments = base.split(delim) if delim else [base]
        created: list[str] = []
        prefix = ""
        for segment in segments:
            prefix = f"{prefix}{delim}{segment}" if prefix else segment
            if prefix in existing or prefix.upper() == "INBOX":
                continue
            _ok(*self.imap.create(quote(prefix)), f"CREATE {imap_utf7.decode(prefix)}")
            with contextlib.suppress(Exception):
                self.imap.subscribe(quote(prefix))
            created.append(prefix)
        return created

    def create_folder(self, mailbox_raw: str, folders: Optional[list[Folder]] = None) -> list[str]:
        """CREATE ``mailbox_raw`` plus any missing parent, then subscribe it.

        Returns the raw names actually created, so the caller reports what changed instead of claiming
        success on a folder the server already had. A name refused for living outside the personal
        namespace is retried once inside it."""
        known = folders if folders is not None else self.list_folders()
        delim = next((f.delimiter for f in known if f.delimiter), "")
        mailbox_raw = self._with_delimiter(mailbox_raw, delim)
        candidates = [mailbox_raw]
        prefix = self._namespace_prefix(known, delim)
        if prefix and not mailbox_raw.upper().startswith(prefix.upper()):
            candidates.append(prefix + mailbox_raw)
        for base in candidates:
            try:
                return self._create_tree(base, known, delim)
            except ImapError as exc:
                if base != candidates[-1] and "namespace" in str(exc).lower():
                    continue
                raise
        return []

    def rename_folder(self, old_raw: str, new_raw: str, folders: Optional[list[Folder]] = None) -> None:
        """RENAME a mailbox. Per RFC 3501 a server renames its children too.

        Same namespace handling as :meth:`create_folder`: a target name refused outside the personal
        namespace is retried inside it."""
        known = folders if folders is not None else self.list_folders()
        delim = next((f.delimiter for f in known if f.delimiter), "")
        new_raw = self._with_delimiter(new_raw, delim)
        candidates = [new_raw]
        prefix = self._namespace_prefix(known, delim)
        if prefix and not new_raw.upper().startswith(prefix.upper()):
            candidates.append(prefix + new_raw)
        for target in candidates:
            try:
                _ok(*self.imap.rename(quote(old_raw), quote(target)), f"RENAME {imap_utf7.decode(old_raw)}")
            except ImapError as exc:
                if target != candidates[-1] and "namespace" in str(exc).lower():
                    continue
                raise
            self.selected = None
            return

    # -- selection / search -------------------------------------------------------------------------
    def select(self, mailbox_raw: str, *, readonly: bool) -> int:
        """Select a mailbox and return its UIDVALIDITY."""
        typ, data = self.imap.select(quote(mailbox_raw), readonly=readonly)
        _ok(typ, data, f"SELECT {mailbox_raw}")
        self.selected = mailbox_raw
        _, values = self.imap.response("UIDVALIDITY")
        try:
            return int(values[0]) if values and values[0] else 0
        except (TypeError, ValueError):
            return 0

    def max_uid(self) -> int:
        typ, data = self.imap.uid("search", None, "ALL")
        uids = _ok(typ, data, "UID SEARCH ALL")[0].split()
        return int(uids[-1]) if uids else 0

    def uids_after(self, watermark: int) -> list[int]:
        typ, data = self.imap.uid("search", None, f"UID {watermark + 1}:*")
        found = (_ok(typ, data, "UID SEARCH")[0] or b"").split()
        return sorted(u for u in (int(x) for x in found) if u > watermark)

    def find_by_message_id(self, message_id: str) -> list[int]:
        """UIDs in the selected mailbox whose Message-ID header matches (exact id, angle brackets kept)."""
        if not message_id or not message_id.isascii():
            return []
        typ, data = self.imap.uid("search", None, "HEADER", "Message-ID", quote(message_id))
        return [int(x) for x in (_ok(typ, data, "UID SEARCH HEADER")[0] or b"").split()]

    def search(self, term: str, *, unseen_only: bool = False) -> list[int]:
        """UIDs of the selected mailbox whose FROM or SUBJECT contains ``term``.

        Accented terms go through ``CHARSET UTF-8``; an empty term matches everything."""
        criteria: list[str] = []
        term = (term or "").strip()
        if term:
            if not term.isascii():
                criteria += ["CHARSET", "UTF-8"]
            criteria += ["OR", "FROM", quote(term), "SUBJECT", quote(term)]
        if unseen_only:
            criteria.append("UNSEEN")
        typ, data = self.imap.uid("search", None, *(criteria or ["ALL"]))
        return sorted(int(x) for x in (_ok(typ, data, "UID SEARCH")[0] or b"").split())

    def headers(self, uids: list[int], fields: str = "FROM SUBJECT DATE", *, batch: int = 100) -> list[dict]:
        """Fetch header fields for several UIDs in one round trip.

        Returns ``{"uid", "flags", "raw"}`` per message, so a caller can list what a folder holds without
        downloading a single body."""
        out: list[dict] = []
        for start in range(0, len(uids), batch):
            sequence = ",".join(str(u) for u in uids[start:start + batch])
            typ, data = self.imap.uid("fetch", sequence, f"(UID FLAGS BODY.PEEK[HEADER.FIELDS ({fields})])")
            for part in _ok(typ, data, "UID FETCH HEADERS"):
                if not isinstance(part, tuple) or len(part) < 2:
                    continue
                meta = part[0] or b""
                uid_match = re.search(rb"\bUID (\d+)", meta)
                flags_match = re.search(rb"FLAGS \(([^)]*)\)", meta)
                out.append({"uid": int(uid_match.group(1)) if uid_match else 0,
                            "flags": {f.lower() for f in (flags_match.group(1).decode("ascii", "replace").split()
                                                          if flags_match else [])},
                            "raw": part[1]})
        return out

    # -- fetch ----------------------------------------------------------------------------------------
    def _fetch_items(self, uid: int, items: str) -> list[bytes]:
        typ, data = self.imap.uid("fetch", str(uid), items)
        return [part[1] for part in _ok(typ, data, "UID FETCH") if isinstance(part, tuple) and len(part) > 1]

    def size_of(self, uid: int) -> Optional[int]:
        typ, data = self.imap.uid("fetch", str(uid), "(RFC822.SIZE)")
        for part in _ok(typ, data, "UID FETCH SIZE"):
            blob = part[0] if isinstance(part, tuple) else part
            match = re.search(rb"RFC822\.SIZE (\d+)", blob or b"")
            if match:
                return int(match.group(1))
        return None

    def fetch_raw(self, uid: int, max_bytes: int) -> Optional[bytes]:
        """Whole message without setting \\Seen; oversized messages keep headers + the start of the body."""
        size = self.size_of(uid)
        if size is None:
            return None
        if size <= max_bytes:
            parts = self._fetch_items(uid, "(BODY.PEEK[])")
            return parts[0] if parts else None
        parts = self._fetch_items(uid, f"(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{max_bytes}>)")
        return b"".join(parts) if parts else None

    def fetch_header_field(self, uid: int, field: str) -> str:
        parts = self._fetch_items(uid, f"(BODY.PEEK[HEADER.FIELDS ({field.upper()})])")
        text = (parts[0] if parts else b"").decode("utf-8", "replace")
        _, _, value = text.partition(":")
        return value.strip()

    # -- mutations -------------------------------------------------------------------------------------
    def move(self, uid: int, dest_raw: str) -> None:
        if "MOVE" in self.caps:
            typ, data = self.imap.uid("MOVE", str(uid), quote(dest_raw))
            _ok(typ, data, "UID MOVE")
            return
        if "UIDPLUS" not in self.caps:
            raise ImapError("serveur sans MOVE ni UIDPLUS : déplacement refusé (risque d'expunge global)")
        _ok(*self.imap.uid("copy", str(uid), quote(dest_raw)), "UID COPY")
        _ok(*self.imap.uid("store", str(uid), "+FLAGS.SILENT", r"(\Deleted)"), "UID STORE")
        _ok(*self.imap.uid("expunge", str(uid)), "UID EXPUNGE")

    def move_many(self, uids: list[int], dest_raw: str, *, batch: int = 200) -> int:
        """Move several UIDs of the selected mailbox at once (bulk merge). Returns how many were moved.

        MOVE is preferred; the COPY/\\Deleted/UID EXPUNGE fallback is only used on servers that advertise
        UIDPLUS, so an interrupted merge can never expunge unrelated messages."""
        moved = 0
        for start in range(0, len(uids), batch):
            sequence = ",".join(str(u) for u in uids[start:start + batch])
            if "MOVE" in self.caps:
                _ok(*self.imap.uid("MOVE", sequence, quote(dest_raw)), "UID MOVE")
            else:
                if "UIDPLUS" not in self.caps:
                    raise ImapError("serveur sans MOVE ni UIDPLUS : déplacement de masse refusé")
                _ok(*self.imap.uid("copy", sequence, quote(dest_raw)), "UID COPY")
                _ok(*self.imap.uid("store", sequence, "+FLAGS.SILENT", r"(\Deleted)"), "UID STORE")
                _ok(*self.imap.uid("expunge", sequence), "UID EXPUNGE")
            moved += min(batch, len(uids) - start)
        return moved

    def set_flag(self, uid: int, flag: str, on: bool) -> None:
        _ok(*self.imap.uid("store", str(uid), "+FLAGS.SILENT" if on else "-FLAGS.SILENT", f"({flag})"), "UID STORE")

    def append(self, mailbox_raw: str, flags: str, message: bytes) -> Optional[int]:
        typ, data = self.imap.append(quote(mailbox_raw), flags, imaplib.Time2Internaldate(time.time()), message)
        _ok(typ, data, "APPEND")
        match = _APPENDUID_RE.search(b" ".join(d for d in data if isinstance(d, bytes)))
        return int(match.group(1)) if match else None

    def delete_own_draft(self, uid: int, ref: str) -> bool:
        """Remove one draft in the selected drafts mailbox, only if it carries our X-Mail-Agent-Ref for ``ref``."""
        if "UIDPLUS" not in self.caps:
            return False
        if self.fetch_header_field(uid, "X-Mail-Agent-Ref") != ref:
            return False
        _ok(*self.imap.uid("store", str(uid), "+FLAGS.SILENT", r"(\Deleted)"), "UID STORE")
        _ok(*self.imap.uid("expunge", str(uid)), "UID EXPUNGE")
        return True

    # -- push -------------------------------------------------------------------------------------------
    def idle(self, max_seconds: float, read_timeout: float = 600.0) -> bool:
        """IDLE on the selected mailbox. True when the server announced new mail, False on cycle timeout.

        Dovecot sends ``* OK Still here`` every ~2 min, so ``read_timeout`` only fires on a dead link; the
        caller then drops the connection. Teardown unblocks the read through :meth:`abort`.
        """
        if "IDLE" not in self.caps:
            time.sleep(min(max_seconds, 60))
            return True
        imap = self.imap
        tag = imap._new_tag()
        imap.send(tag + b" IDLE\r\n")
        line = imap.readline()
        if not line.startswith(b"+"):
            raise ImapError(f"IDLE refusé : {line[:200]!r}")
        imap.socket().settimeout(read_timeout)
        deadline = time.monotonic() + max_seconds
        announced = False
        try:
            while time.monotonic() < deadline:
                line = imap.readline()
                if not line:
                    raise ImapError("connexion fermée pendant IDLE")
                if _EXISTS_RE.match(line):
                    announced = True
                    break
            imap.send(b"DONE\r\n")
            while True:
                line = imap.readline()
                if not line:
                    raise ImapError("connexion fermée après IDLE")
                if line.startswith(tag + b" "):
                    if not line.startswith(tag + b" OK"):
                        raise ImapError(f"fin d'IDLE refusée : {line[:200]!r}")
                    break
        finally:
            with contextlib.suppress(Exception):
                imap.socket().settimeout(self.settings.timeout)
        return announced
