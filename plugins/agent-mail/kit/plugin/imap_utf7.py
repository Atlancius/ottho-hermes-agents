"""IMAP modified UTF-7 (RFC 3501 §5.1.3) for mailbox names such as ``Reçus`` or ``Comptabilité``."""

import base64


def encode(name: str) -> str:
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            raw = "".join(pending).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)


def decode(name: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(name):
        if name[i] != "&":
            out.append(name[i])
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:  # malformed: keep verbatim rather than guess
            out.append(name[i:])
            break
        chunk = name[i + 1:end]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            out.append(base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-16-be"))
        i = end + 1
    return "".join(out)
