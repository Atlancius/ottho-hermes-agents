"""Owner notifications: deterministic Telegram message built from the mail record, sent with the profile's bot."""

from __future__ import annotations

import json
import logging
import urllib.request

from . import settings

logger = logging.getLogger(__name__)
_TELEGRAM_LIMIT = 4000


def _chunks(text: str) -> list[str]:
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > _TELEGRAM_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:_TELEGRAM_LIMIT])
            line = line[_TELEGRAM_LIMIT:]
        if len(current) + len(line) > _TELEGRAM_LIMIT:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)
    return chunks


def send_owner(text: str) -> bool:
    """Blocking send to the owner's Telegram chat. Never logs the token or the request URL."""
    token, chat_id = settings.secret("TELEGRAM_BOT_TOKEN"), settings.owner_chat_id()
    if not token or not chat_id:
        logger.error("[mail-agent] notification impossible : TELEGRAM_BOT_TOKEN ou chat du propriétaire absent")
        return False
    ok = True
    for chunk in _chunks(text):
        payload = json.dumps({"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}).encode()
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # honours HTTPS_PROXY
                ok = ok and bool(json.loads(response.read() or b"{}").get("ok"))
        except Exception as exc:
            logger.error("[mail-agent] envoi Telegram en échec : %s", type(exc).__name__)
            ok = False
    return ok


def _sender(rec: dict) -> str:
    name, addr = rec.get("from_name") or "", rec.get("from") or ""
    return f"{name} <{addr}>" if name else addr


def compose(rec: dict) -> str:
    decision = rec.get("decision") or {}
    draft = rec.get("draft") or {}
    live = rec.get("mode") == "live"
    status = "À répondre" if decision.get("needs_reply") else "À lire"
    lines = [f"{rec['ref']} · {status} · priorité {decision.get('priority', 'normale')}",
             f"De : {_sender(rec)}",
             f"Objet : {rec.get('subject') or '(sans objet)'}"]
    if decision:
        brand = settings.brand_label(decision.get("brand") or "?")
        lines.append(f"Marque : {brand} ({decision.get('register', '?')})")
        folder = decision.get("folder") or decision.get("category")
        lines.append(f"Classé : {folder} · catégorie {decision.get('category', '?')}"
                     + ("" if live else " (mode shadow : rien n'a bougé dans la boîte)"))
        lines.append(f"Résumé : {decision.get('summary', '')}")
    else:
        lines.append("Classement : absent, l'agent n'a pas trié ce mail.")
    if rec.get("server_spam"):
        lines.append("Repêché : le filtre antispam du serveur l'avait mis dans Junk.")
    if rec.get("notify_reason"):
        lines.append(f"Attention : {rec['notify_reason']}")
    if rec.get("attachments"):
        lines.append("Pièces jointes : " + ", ".join(a["name"] for a in rec["attachments"]))
    if draft.get("body"):
        where = "dans Brouillons, à valider et envoyer toi-même" if draft.get("saved") else "non enregistré (shadow)"
        lines += ["", f"Brouillon ({where}) :", "────────", draft["body"].strip(), "────────"]
    if rec.get("agent_note"):
        lines += ["", f"Note de l'agent : {rec['agent_note'].strip()[:800]}"]
    lines += ["", f"Pour corriger : « {rec['ref']} plus court », « {rec['ref']} classe dans … », « {rec['ref']} pas de réponse »."]
    return "\n".join(lines)


def should_notify(rec: dict) -> bool:
    decision = rec.get("decision") or {}
    return bool(decision.get("needs_reply") or rec.get("notify_reason") or rec.get("draft") or not decision)


def compose_failure(rec: dict, reason: str) -> str:
    where = (f"Il a été classé dans {rec['current_folder']}." if rec.get("current_folder")
             else "Il est resté dans la boîte de réception, non lu.")
    return (f"{rec.get('ref', '?')} · traitement en échec\nDe : {_sender(rec)}\n"
            f"Objet : {rec.get('subject') or '(sans objet)'}\nCause : {reason}\n{where}")
