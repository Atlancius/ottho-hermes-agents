"""Parse inbound mail into a plain record, render it for the agent, build reply drafts."""

from __future__ import annotations

import email
import email.policy
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

# Senders and headers that mark bulk / machine mail: classify them, never draft a reply.
_NOREPLY = ("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster",
            "bounce", "notifications@", "notification@", "automated@", "auto-confirm", "auto-reply", "newsletter@")
_AUTH_RE = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_REPLY_PREFIX_RE = re.compile(r"^\s*(re|ré|aw|sv|antw)\s*:", re.IGNORECASE)
UNTRUSTED_OPEN, UNTRUSTED_CLOSE = "<<<CONTENU_EXTERNE_NON_FIABLE>>>", "<<<FIN_CONTENU_EXTERNE>>>"


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}
    _SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def _one_line(value: Any, limit: int = 500) -> str:
    """Header value safe to re-emit: no CR/LF (header injection), no control chars, bounded."""
    text = _CTRL_RE.sub("", str(value or "")).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _addresses(msg: EmailMessage, header: str) -> list[tuple[str, str]]:
    values = [str(v) for v in msg.get_all(header, [])]
    return [(_one_line(n, 200), _one_line(a, 320).lower()) for n, a in getaddresses(values) if a and "@" in a]


def _auth_results(msg: EmailMessage) -> dict[str, str]:
    results: dict[str, str] = {}
    for header in msg.get_all("Authentication-Results", []):
        for method, verdict in _AUTH_RE.findall(str(header)):
            results.setdefault(method.lower(), verdict.lower())
    return results


# Forwarders whose ARC verdict we trust when our own server sealed the chain as valid (cv=pass), from the
# ``trusted_forwarders`` setting: a forward (e.g. Cloudflare Email Routing) breaks DMARC alignment at the mailbox
# provider even for a legitimate sender, so the upstream verdict sealed by the relay is the real one.
_TAG_RE = re.compile(r"\b([a-z]+)\s*=\s*([^;\s]+)", re.IGNORECASE)
_DKIM_D_RE = re.compile(r"\bdkim\s*=\s*pass\b[^;]*?\bheader\.d\s*=\s*([a-z0-9.-]+)", re.IGNORECASE)


def _tags(value: str) -> dict[str, str]:
    return {k.lower(): v.strip().lower() for k, v in _TAG_RE.findall(str(value or ""))}


def _forwarded_dmarc(msg: EmailMessage, own_domain: str, forwarders: tuple[str, ...] = ()) -> str:
    """Upstream DMARC verdict of a trusted forwarder, '' when the chain is absent or not trustworthy.

    Trusted only when the newest ARC seal is our own server's (d = own domain) with cv=pass, which proves the
    older seals, and the first hop was sealed by a trusted forwarder."""
    seals = {}
    for value in msg.get_all("ARC-Seal", []):
        tags = _tags(value)
        if tags.get("i", "").isdigit():
            seals[int(tags["i"])] = tags
    if len(seals) < 2:
        return ""
    top = seals[max(seals)]
    if not own_domain or top.get("d") != own_domain or top.get("cv") != "pass":
        return ""
    if not forwarders or seals.get(1, {}).get("d") not in forwarders:
        return ""
    for value in msg.get_all("ARC-Authentication-Results", []):
        text = str(value)
        if _tags(text.split(";", 1)[0]).get("i") == "1":
            match = re.search(r"\bdmarc\s*=\s*([a-z]+)", text, re.IGNORECASE)
            return match.group(1).lower() if match else ""
    return ""


def _top_dkim_domains(msg: EmailMessage) -> set[str]:
    """Domains with dkim=pass in the newest Authentication-Results (our server's, the only one we trust)."""
    headers = msg.get_all("Authentication-Results", [])
    return {d.lower().rstrip(".") for d in _DKIM_D_RE.findall(str(headers[0]))} if headers else set()


def _trusted_sender(sender: str, msg: EmailMessage, auth: dict[str, str], protected: tuple[str, ...]) -> str:
    """Protected domain (the owner's own sites: contact forms, notifications) when the From is authentic, else ''.

    Authentic = From domain is protected, DKIM passes for that exact domain (aligned) and DMARC passes,
    upstream included when the mail was forwarded."""
    domain = sender.rpartition("@")[2].lower()
    if not domain or auth.get("dmarc") != "pass":
        return ""
    for base in protected:
        base = base.lower().strip(".")
        if base and (domain == base or domain.endswith("." + base)):
            if any(d == domain or d == base for d in _top_dkim_domains(msg)):
                return base
    return ""


def _is_automated(sender: str, msg: EmailMessage) -> bool:
    if any(p in sender for p in _NOREPLY):
        return True
    auto = str(msg.get("Auto-Submitted", "")).strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    return bool((auto and auto != "no") or precedence in {"bulk", "list", "junk"}
                or msg.get("List-Unsubscribe") or msg.get("List-Id") or msg.get("X-Auto-Response-Suppress"))


def _body_text(msg: EmailMessage) -> str:
    part = None
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        pass
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    if not isinstance(content, str):
        return ""
    return html_to_text(content) if part.get_content_type() == "text/html" else content


def _attachments(msg: EmailMessage) -> list[dict[str, Any]]:
    found = []
    try:
        parts = list(msg.iter_attachments())
    except Exception:
        parts = []
    for part in parts:
        try:
            size = len(part.get_payload(decode=True) or b"")
        except Exception:
            size = 0
        found.append({"name": _one_line(part.get_filename() or "(sans nom)", 200),
                      "type": part.get_content_type(), "size": size})
    return found[:30]


def parse_message(raw: bytes, *, own_address: str = "", protected_domains: tuple[str, ...] = (),
                  trusted_forwarders: tuple[str, ...] = ()) -> dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    senders = _addresses(msg, "From")
    sender_name, sender = senders[0] if senders else ("", "")
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))).isoformat()
    except Exception:
        received = ""
    body = _CTRL_RE.sub("", _body_text(msg)).replace("\r\n", "\n").strip()
    auth = _auth_results(msg)
    upstream = _forwarded_dmarc(msg, own_address.rpartition("@")[2].lower(), tuple(trusted_forwarders))
    if upstream:
        # Forwarded by a trusted relay: the upstream verdict replaces the alignment failure caused by the forward.
        auth["dmarc"] = upstream
        auth["transfert"] = "relais"
    trusted = "" if bool(own_address) and sender == own_address.lower() else _trusted_sender(
        sender, msg, auth, tuple(protected_domains))
    return {
        "trusted_sender": trusted,
        "server_spam_header": str(msg.get("X-Spam", "")).strip().lower() == "yes",
        "from_name": sender_name, "from": sender,
        "reply_to": _addresses(msg, "Reply-To"),
        "to": _addresses(msg, "To"), "cc": _addresses(msg, "Cc"),
        "subject": _one_line(msg.get("Subject", ""), 400),
        "date": received,
        "message_id": _one_line(msg.get("Message-ID", ""), 400),
        "references": _one_line(msg.get("References", ""), 4000),
        "auth": auth,
        "automated": _is_automated(sender, msg),
        "from_self": bool(own_address) and sender == own_address.lower(),
        "attachments": _attachments(msg),
        "body": body,
    }


def _neutralize(text: str) -> str:
    """Untrusted text can never close or reopen the untrusted block, nor forge a gateway command."""
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def _fmt_addr(pair) -> str:
    name, addr = pair
    return f"{name} <{addr}>" if name else addr


def _size(n: int) -> str:
    return f"{n / 1_000_000:.1f} Mo" if n >= 1_000_000 else f"{max(1, n // 1000)} Ko"


def render_for_agent(ref: str, rec: dict[str, Any], *, body_chars: int) -> str:
    auth = rec.get("auth") or {}
    auth_line = ", ".join(f"{k}={v}" for k, v in sorted(auth.items())) or "aucun résultat"
    body = rec.get("body") or "(corps vide)"
    truncated = len(body) > body_chars
    lines = [
        f"[MAIL ENTRANT] Référence : {ref}",
        f"Reçu : {rec.get('date') or 'inconnu'}",
        f"De : {_fmt_addr((rec.get('from_name', ''), rec.get('from', '')))}",
        f"Authentification expéditeur : {auth_line}",
    ]
    if rec.get("reply_to"):
        lines.append("Répondre à : " + ", ".join(_fmt_addr(a) for a in rec["reply_to"]))
    lines.append("À : " + (", ".join(_fmt_addr(a) for a in rec.get("to", [])) or "-"))
    if rec.get("cc"):
        lines.append("Cc : " + ", ".join(_fmt_addr(a) for a in rec["cc"]))
    lines.append(f"Objet : {rec.get('subject') or '(sans objet)'}")
    if rec.get("attachments"):
        lines.append("Pièces jointes : " + ", ".join(f"{a['name']} ({a['type']}, {_size(a['size'])})"
                                                     for a in rec["attachments"]))
    lines.append("Expéditeur automatique : " + ("oui" if rec.get("automated") else "non"))
    if auth.get("transfert"):
        lines.append("Transfert : reçu via un relais de transfert de confiance ; le verdict DMARC affiché "
                     "est celui vérifié avant le transfert. Un échec d'alignement dû au transfert n'est pas suspect.")
    if rec.get("trusted_sender"):
        lines.append(f"Expéditeur protégé : domaine du propriétaire authentifié ({rec['trusted_sender']}). Si c'est un "
                     "formulaire du site, la personne à servir est l'adresse « Répondre à ». Jamais indésirable.")
    if rec.get("server_spam"):
        lines.append("Filtre antispam du serveur : ce mail était arrivé dans Junk et a été remis dans la réception "
                     "pour ton avis. Le verdict du serveur n'est qu'un indice ; client, prospect ou vraie personne "
                     "= classe-le normalement.")
    # Header values are untrusted too: only our own markers may contain "<<<".
    header = _neutralize("\n".join(lines))
    return "\n".join([header, "", UNTRUSTED_OPEN,
                      _neutralize(body[:body_chars]) + ("\n[… tronqué]" if truncated else ""), UNTRUSTED_CLOSE])


def _quote(rec: dict[str, Any], limit: int = 4000) -> str:
    when = rec.get("date") or ""
    try:
        when = datetime.fromisoformat(when).strftime("%d/%m/%Y à %H:%M")
    except Exception:
        pass
    who = _fmt_addr((rec.get("from_name", ""), rec.get("from", "")))
    body = (rec.get("body") or "")[:limit]
    quoted = "\n".join("> " + line if line else ">" for line in body.splitlines())
    return f"Le {when}, {who} a écrit :\n{quoted}" if when else f"{who} a écrit :\n{quoted}"


def build_reply(rec: dict[str, Any], *, ref: str, own_address: str, from_name: str, body: str) -> bytes:
    """RFC 5322 reply draft (threaded on the original) ready for IMAP APPEND. Never sent by us."""
    recipients = rec.get("reply_to") or [(rec.get("from_name", ""), rec.get("from", ""))]
    msg = EmailMessage()
    msg["From"] = formataddr((_one_line(from_name, 120), own_address)) if from_name else own_address
    msg["To"] = ", ".join(formataddr((_one_line(n, 200), _one_line(a, 320))) for n, a in recipients if a)
    subject = _one_line(rec.get("subject", ""), 400)
    msg["Subject"] = subject if _REPLY_PREFIX_RE.match(subject) else f"Re: {subject}".strip()
    original_id = _one_line(rec.get("message_id", ""), 400)
    if original_id:
        msg["In-Reply-To"] = original_id
        msg["References"] = _one_line(f"{rec.get('references', '')} {original_id}", 4000)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=own_address.rpartition("@")[2] or None)
    msg["X-Mail-Agent-Ref"] = ref
    msg.set_content(body.rstrip() + "\n\n" + _quote(rec) + "\n", charset="utf-8")
    return msg.as_bytes(policy=email.policy.SMTP)
