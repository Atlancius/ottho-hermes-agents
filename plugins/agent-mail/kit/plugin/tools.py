"""``mail_agent`` toolset.

Inside a mail session (platform ``mail_inbox``) every tool is bound to that session's mail: a hostile mail can at
worst mis-file itself or produce a bad draft of itself. From the owner's Telegram chat the tools accept any reference.
Nothing here can send mail.
"""

from __future__ import annotations

import time
from email import message_from_bytes
from email.header import decode_header, make_header
from typing import Any, Optional

from tools.registry import tool_error, tool_result

from . import imap_utf7, knowledge, settings
from .facts import Facts
from .imap_client import Folder, ImapError, Mailbox
from .mailparse import build_reply, render_for_agent
from .store import Store, valid_ref

_store: Optional[Store] = None
_facts: Optional[Facts] = None
_OPERATOR_SURFACES = {"telegram", "cli", "local", "tui", "desktop"}


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(settings.home() / "mail-agent")
    return _store


def facts() -> Facts:
    global _facts
    if _facts is None:
        _facts = Facts(settings.home() / "mail-agent" / "facts.json")
    return _facts


def _surface() -> tuple[str, str]:
    """(surface, chat_id). The gateway binds HERMES_SESSION_PLATFORM per session; a bare ``hermes chat`` binds nothing.
    An empty surface counts as the operator CLI only outside a gateway process: inside one it stays unknown (refused)."""
    try:
        from gateway.session_context import get_session_env, session_context_engaged
        surface = get_session_env("HERMES_SESSION_PLATFORM", "") or get_session_env("HERMES_SESSION_SOURCE", "")
        if not surface and not session_context_engaged():
            surface = "cli"
        return surface.strip().lower(), get_session_env("HERMES_SESSION_CHAT_ID", "")
    except Exception:
        return "", ""


def _authorize(ref: str, *, operator_only: bool = False) -> Optional[str]:
    """Error text when the caller may not act on ``ref``; None when allowed."""
    platform, chat_id = _surface()
    if platform == settings.PLATFORM:
        if operator_only:
            return "outil réservé au propriétaire (conversation Telegram)"
        return None if chat_id == f"mail:{ref}" else "dans un traitement de mail, seul ce mail-là est accessible"
    if platform in _OPERATOR_SURFACES:
        return None
    return f"surface non autorisée : {platform or 'inconnue'}"


def _record(ref: str) -> tuple[Optional[dict], Optional[str]]:
    ref = str(ref or "").strip().upper()
    if not valid_ref(ref):
        return None, "référence invalide (format attendu : M1234)"
    denied = _authorize(ref)
    if denied:
        return None, denied
    rec = store().get(ref)
    return (rec, None) if rec else (None, f"{ref} inconnu (seuls les mails reçus depuis l'activation sont suivis)")


def _locate(mb: Mailbox, rec: dict) -> tuple[str, int]:
    """Select the mailbox currently holding the mail (read-write) and return (mailbox_raw, uid)."""
    inbox = settings.config()["imap"]["inbox"]
    candidates = [rec.get("current_folder_raw") or inbox]
    if inbox not in candidates:
        candidates.append(inbox)
    for mailbox_raw in candidates:
        mb.select(mailbox_raw, readonly=False)
        uids = mb.find_by_message_id(rec.get("message_id", ""))
        if not uids and not rec.get("message_id") and mailbox_raw == inbox and rec.get("inbox_uid"):
            uids = [int(rec["inbox_uid"])]
        if uids:
            return mailbox_raw, uids[-1]
    # the mail may have been filed elsewhere since it was recorded: sweep the folders before giving up
    wanted = rec.get("message_id", "")
    if wanted:
        for folder in mb.list_folders():
            if folder.raw in candidates or "\\noselect" in folder.flags:
                continue
            mb.select(folder.raw, readonly=False)
            uids = mb.find_by_message_id(wanted)
            if uids:
                return folder.raw, uids[-1]
    raise ImapError("mail introuvable (déplacé ou supprimé manuellement ?)")


_SUPPLIER_CATEGORIES = ("fournisseurs", "banque", "livraisons")


def _supplier_target(rec: dict, category: str, args: dict) -> tuple[str, str, Optional[str]]:
    """(supplier, kind, error). A known supplier domain wins for its orders, deliveries and payments;
    otherwise the agent's ``supplier`` applies to the ``fournisseurs`` category only."""
    mapped, default_kind = settings.supplier_for(rec.get("from", ""))
    supplier = ""
    if mapped and category in _SUPPLIER_CATEGORIES:
        supplier = mapped
    elif category == "fournisseurs":
        raw = str(args.get("supplier") or "").replace("/", " ").replace("\\", " ").replace(".", " ")
        supplier = " ".join(raw.split())[:80]
    if not supplier:
        return "", "", None
    kinds = settings.supplier_kinds()
    wanted = " ".join(str(args.get("supplier_kind") or "").split())
    if not wanted:
        wanted = {"banque": "Paiements", "livraisons": "Suivis"}.get(category, "") or default_kind
    if wanted:
        match = next((k for k in kinds if k.casefold() == wanted.casefold()), "")
        if not match:
            return "", "", f"supplier_kind doit valoir : {', '.join(kinds)} (ou rester vide)"
        wanted = match
    return supplier, wanted, None


def _protected_refusal(rec: dict, action: str) -> Optional[str]:
    """A mail session may never junk or quarantine an authenticated mail from the owner's own domains (site forms).
    The owner (Telegram, CLI) keeps the last word."""
    if not rec.get("trusted_sender") or _surface()[0] != settings.PLATFORM:
        return None
    return (f"expéditeur protégé ({rec['trusted_sender']}, domaine du propriétaire authentifié, formulaire du site) : "
            f"interdit de {action}. Classe-le dans `clients` si c'est une demande, sinon dans `outils`.")


def _enum(value: Any, allowed: tuple, field: str) -> tuple[Optional[str], Optional[str]]:
    text = str(value or "").strip().lower()
    return (text, None) if text in allowed else (None, f"{field} doit valoir : {', '.join(allowed)}")


# -- handlers -------------------------------------------------------------------------------------------
def mail_get(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    limits = settings.config()["limits"]
    return tool_result(ref=rec["ref"], status=rec.get("status"), decision=rec.get("decision"),
                       draft=rec.get("draft"), notify_reason=rec.get("notify_reason"),
                       mail=render_for_agent(rec["ref"], rec, body_chars=int(limits["body_chars"])))


def mail_triage(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    cats = settings.categories()
    category = str(args.get("category") or "").strip()
    if category not in cats:
        return tool_error(f"catégorie inconnue. Valeurs possibles : {', '.join(cats) or 'aucune configurée'}")
    protected = _protected_refusal(rec, "classer en indésirables") if category == "indesirables" else None
    if protected:
        return tool_error(protected)
    brand, e1 = _enum(args.get("brand"), settings.brands(), "brand")
    register, e2 = _enum(args.get("register"), settings.registers(), "register")
    priority, e3 = _enum(args.get("priority") or "normale", settings.PRIORITIES, "priority")
    if e1 or e2 or e3:
        return tool_error(e1 or e2 or e3)
    needs_reply = bool(args.get("needs_reply"))
    summary = " ".join(str(args.get("summary") or "").split())[:600]
    cfg = settings.config()
    supplier, kind, error = _supplier_target(rec, category, args)
    if error:
        return tool_error(error)
    if supplier and "fournisseurs" in cats:
        category = "fournisseurs"
    # Mail awaiting the owner's reply stays in the inbox (starred) when configured: the inbox is his to-do list.
    keep_in_inbox = needs_reply and bool(cfg.get("reply_keeps_inbox"))
    folder_name = str(cfg["imap"]["inbox"] if keep_in_inbox else cats[category].get("folder") or "").strip()
    if supplier and not keep_in_inbox:
        root = settings.folder_slot("suppliers", "Fournisseurs")
        folder_name = f"{root}/{supplier}/{kind}" if kind else f"{root}/{supplier}"
    decision = {"category": category, "folder": "Boîte de réception" if keep_in_inbox else folder_name,
                "needs_reply": needs_reply, "brand": brand, "register": register, "priority": priority,
                "summary": summary, "decided_at": time.time()}
    if supplier:
        decision.update(supplier=supplier, supplier_kind=kind)
    fields: dict[str, Any] = {"decision": decision, "status": "triaged"}
    if settings.live():
        try:
            with Mailbox(settings.imap_settings()) as mb:
                folders = mb.list_folders()
                dest = mb.resolve_folder(folder_name, folders)
                if dest is None and supplier and not keep_in_inbox:
                    mb.create_folder(imap_utf7.encode(folder_name), folders)
                    dest = mb.resolve_folder(folder_name)
                if dest is None:
                    return tool_error(f"dossier IMAP « {folder_name} » absent du serveur")
                source_raw, uid = _locate(mb, rec)
                mb.set_flag(uid, r"\Flagged", needs_reply)
                if dest.raw != source_raw:
                    mb.move(uid, dest.raw)
                fields.update(current_folder=dest.name, current_folder_raw=dest.raw)
        except ImapError as exc:
            store().update(rec["ref"], last_error=str(exc))
            return tool_error(f"IMAP : {exc}")
    store().update(rec["ref"], **fields)
    return tool_result(ok=True, ref=rec["ref"], mode="live" if settings.live() else "shadow",
                       folder=folder_name, flagged=needs_reply)


def mail_save_draft(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    if rec.get("suspect"):
        return tool_error(f"{rec['ref']} est en quarantaine : aucun brouillon n'est préparé pour un message suspect")
    platform, _chat = _surface()
    if platform == settings.PLATFORM and (rec.get("automated") or rec.get("from_self")):
        return tool_error("pas de brouillon pour un expéditeur automatique ou pour soi-même")
    body = str(args.get("body") or "").strip()
    if not 10 <= len(body) <= 10000:
        return tool_error("le brouillon doit faire entre 10 et 10 000 caractères")
    brand = (rec.get("decision") or {}).get("brand") or settings.UNDETERMINED
    brand_cfg = settings.brand_cfg(brand)
    signature = str(brand_cfg.get("signature") or "").strip()
    if signature and signature not in body:
        body = f"{body}\n\n{signature}"
    draft: dict[str, Any] = {"body": body, "brand": brand, "saved": False, "saved_at": time.time()}
    if settings.live():
        imap = settings.imap_settings()
        message = build_reply(rec, ref=rec["ref"], own_address=imap.address,
                              from_name=str(brand_cfg.get("from_name") or ""), body=body)
        try:
            with Mailbox(imap) as mb:
                drafts = mb.drafts_folder(str(settings.config()["imap"].get("drafts") or ""))
                new_uid = mb.append(drafts.raw, r"(\Draft \Seen)", message)
                mb.select(drafts.raw, readonly=False)
                typ, data = mb.imap.uid("search", None, "HEADER", "X-Mail-Agent-Ref", rec["ref"])
                ours = sorted(int(x) for x in (data[0] or b"").split()) if typ == "OK" and data else []
                keep = new_uid or (ours[-1] if ours else None)
                replaced = sum(mb.delete_own_draft(uid, rec["ref"]) for uid in ours if uid != keep)
            draft.update(saved=True, uid=keep, folder=drafts.name, replaced=replaced)
        except ImapError as exc:
            store().update(rec["ref"], last_error=str(exc))
            return tool_error(f"IMAP : {exc}")
    store().update(rec["ref"], draft=draft)
    return tool_result(ok=True, ref=rec["ref"], saved=draft["saved"], folder=draft.get("folder"),
                       note="brouillon en attente de validation par le propriétaire, aucun envoi")


def mail_discard_draft(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    denied = _authorize(rec["ref"], operator_only=True)
    if denied:
        return tool_error(denied)
    removed = 0
    if settings.live() and (rec.get("draft") or {}).get("saved"):
        try:
            with Mailbox(settings.imap_settings()) as mb:
                drafts = mb.drafts_folder(str(settings.config()["imap"].get("drafts") or ""))
                mb.select(drafts.raw, readonly=False)
                typ, data = mb.imap.uid("search", None, "HEADER", "X-Mail-Agent-Ref", rec["ref"])
                ours = [int(x) for x in (data[0] or b"").split()] if typ == "OK" and data else []
                removed = sum(mb.delete_own_draft(uid, rec["ref"]) for uid in ours)
        except ImapError as exc:
            return tool_error(f"IMAP : {exc}")
    store().update(rec["ref"], draft=None)
    return tool_result(ok=True, ref=rec["ref"], removed=removed)


def mail_notify(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    reason = " ".join(str(args.get("reason") or "").split())[:300]
    if not reason:
        return tool_error("raison obligatoire")
    store().update(rec["ref"], notify_reason=reason)
    return tool_result(ok=True, ref=rec["ref"])


def mail_folders(args: dict, **_: Any) -> str:
    cats = settings.categories()
    result: dict[str, Any] = {"mode": "live" if settings.live() else "shadow",
                              "categories": {k: v.get("folder") for k, v in cats.items()}}
    platform, _chat = _surface()
    if platform != settings.PLATFORM:
        try:
            with Mailbox(settings.imap_settings()) as mb:
                folders = mb.list_folders()
                result["server_folders"] = [f.name for f in folders]
                result["missing"] = [v.get("folder") for v in cats.values()
                                     if not mb.resolve_folder(str(v.get("folder") or ""), folders)]
        except ImapError as exc:
            result["server_error"] = str(exc)
    return tool_result(result)


_KNOWLEDGE_NOTE = ("Contenu interne de la base de connaissances : n'en reprends dans un brouillon que les faits qui répondent au mail, "
                   "jamais de chiffres internes, de stratégie, de fournisseurs ni d'informations sur d'autres clients.")


def knowledge_search(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    query = " ".join(str(args.get("query") or "").split())[:300]
    if not query:
        return tool_error("requête vide")
    try:
        limit = max(1, min(int(args.get("limit") or 5), 10))
    except (TypeError, ValueError):
        limit = 5
    kb = knowledge.get(settings.config())
    results = kb.search(query, limit=limit)
    from_owner = knowledge.search_facts(facts().all(), query, limit=limit)
    return tool_result(faits_proprietaire=from_owner, resultats=results, pages_indexees=len(kb.pages), note=_KNOWLEDGE_NOTE
                       + " Les faits_proprietaire ont été confirmés par le propriétaire : ils priment sur une page plus ancienne.")


def knowledge_read(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    path = str(args.get("path") or "").strip()
    if path.startswith("owner/"):
        fact = next((f for f in facts().all() if f"owner/{f['id']}" == path), None)
        return tool_result(fact, note="Fait confirmé par le propriétaire.") if fact else tool_error("fait inconnu ou retiré")
    cfg = settings.config()
    page = knowledge.get(cfg).read(path, int(cfg["knowledge"].get("max_read_chars") or 12000))
    if page is None:
        return tool_error("page inconnue ou hors du périmètre autorisé (utilise un chemin renvoyé par knowledge_search)")
    return tool_result(page, note=_KNOWLEDGE_NOTE)


def owner_fact_save(args: dict, **_: Any) -> str:
    denied = _authorize("M0", operator_only=True)
    if denied:
        return tool_error(denied)
    brand = str(args.get("brand") or "").strip().lower()
    if brand not in settings.fact_brands():
        return tool_error(f"brand doit valoir : {', '.join(settings.fact_brands())}")
    topic = " ".join(str(args.get("topic") or "").split())[:120]
    text = str(args.get("text") or "").strip()[:1500]
    if not topic or len(text) < 3:
        return tool_error("sujet et texte obligatoires")
    fact = facts().add(brand, topic, text)
    replaced = str(args.get("replaces") or "").strip().upper()
    if replaced:
        facts().retire(replaced, replaced_by=fact["id"])
    return tool_result(ok=True, fact=fact, remplace=replaced or None)


def owner_fact_list(args: dict, **_: Any) -> str:
    denied = _authorize("M0", operator_only=True)
    if denied:
        return tool_error(denied)
    brand = str(args.get("brand") or "").strip().lower()
    items = [f for f in facts().all() if not brand or f["brand"] == brand]
    return tool_result(faits=items, total=len(items))


def owner_fact_retire(args: dict, **_: Any) -> str:
    denied = _authorize("M0", operator_only=True)
    if denied:
        return tool_error(denied)
    fact = facts().retire(str(args.get("id") or "").strip().upper())
    return tool_result(ok=True, fact=fact) if fact else tool_error("fait inconnu ou déjà retiré")


def mail_recent(args: dict, **_: Any) -> str:
    denied = _authorize("M0", operator_only=True)
    if denied:
        return tool_error(denied)
    try:
        limit = max(1, min(int(args.get("limit") or 10), 50))
    except (TypeError, ValueError):
        limit = 10
    pending_only = bool(args.get("pending_only"))
    rows = []
    for rec in store().all():
        decision = rec.get("decision") or {}
        if pending_only and not decision.get("needs_reply"):
            continue
        rows.append({"ref": rec["ref"], "date": rec.get("date"), "from": rec.get("from"),
                     "subject": rec.get("subject"), "status": rec.get("status"),
                     "category": decision.get("category"), "needs_reply": decision.get("needs_reply"),
                     "draft_saved": (rec.get("draft") or {}).get("saved")})
        if len(rows) >= limit:
            break
    return tool_result(mails=rows)


# -- filing: read what a folder holds, then file one mail at a time ---------------------------------------
def _decode_headers(raw: bytes) -> dict:
    """Decode a raw header block into readable from/subject/date."""
    message = message_from_bytes(raw or b"")

    def read(name: str, limit: int) -> str:
        value = message.get(name)
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value))).strip()[:limit]
        except Exception:
            return str(value).strip()[:limit]

    return {"from": read("From", 200), "subject": read("Subject", 250), "date": read("Date", 80)}


def _record_by_message_id(message_id: str) -> Optional[dict]:
    if not message_id:
        return None
    for rec in store().all():
        if rec.get("message_id") and rec["message_id"] == message_id:
            return rec
    return None


def _file_one(source_name: str, uid: int, target_name: str, *, create: bool,
              force: bool) -> tuple[Optional[dict], Optional[str]]:
    """Move ONE message into a target folder (created when missing). Returns (result, error).

    A tracked mail still awaiting the owner's reply is left where it is unless ``force`` is set: the inbox is his
    to-do list, and filing it away silently is how a customer ends up unanswered."""
    rec: Optional[dict] = None
    try:
        with Mailbox(settings.imap_settings()) as mb:
            source = mb.resolve_folder(source_name)
            if source is None:
                return None, f"dossier source « {source_name} » introuvable"
            target = mb.resolve_folder(target_name)
            if target is None:
                if not create:
                    return None, f"dossier cible « {target_name} » introuvable (create=true pour le créer)"
                mb.create_folder(imap_utf7.encode(target_name))
                target = mb.resolve_folder(target_name)
                if target is None:
                    return None, f"dossier cible « {target_name} » introuvable après création"
            if source.raw == target.raw:
                return None, f"le mail est déjà dans « {target.name} »"
            mb.select(source.raw, readonly=False)
            message_id = mb.fetch_header_field(uid, "Message-ID")
            if not message_id:
                return None, f"aucun mail avec l'uid {uid} dans « {source.name} »"
            rec = _record_by_message_id(message_id)
            if rec and (rec.get("decision") or {}).get("needs_reply") and not force:
                return None, (f"{rec['ref']} attend encore une réponse du propriétaire : il reste visible dans la boîte. "
                              "Repasse avec force=true depuis la conversation Telegram si c'est volontaire.")
            mb.move(uid, target.raw)
    except ImapError as exc:
        return None, f"IMAP : {exc}"
    if rec:
        store().update(rec["ref"], current_folder=target.name, current_folder_raw=target.raw)
    return {"uid": uid, "source": source.name, "target": target.name,
            "mail_suivi": rec["ref"] if rec else None}, None


def mail_scan(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    name = " ".join(str(args.get("folder") or "").split()).strip()
    if not name:
        return tool_error("folder obligatoire")
    query = " ".join(str(args.get("query") or "").split())[:120]
    try:
        limit = max(1, min(int(args.get("limit") or 40), 200))
    except (TypeError, ValueError):
        limit = 40
    try:
        with Mailbox(settings.imap_settings()) as mb:
            folder = mb.resolve_folder(name)
            if folder is None:
                return tool_error(f"dossier « {name} » introuvable")
            mb.select(folder.raw, readonly=True)
            uids = mb.search(query, unseen_only=bool(args.get("unseen_only")))
            rows = []
            for item in mb.headers(uids[-limit:]):
                heads = _decode_headers(item["raw"])
                rows.append({"uid": item["uid"], "date": heads["date"], "de": heads["from"],
                             "objet": heads["subject"], "lu": "\\seen" in item["flags"]})
    except ImapError as exc:
        return tool_error(f"IMAP : {exc}")
    rows.reverse()
    return tool_result(dossier=folder.name, total=len(uids), affiches=len(rows), mails=rows)


def mail_move(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    source_name = " ".join(str(args.get("folder") or "").split()).strip()
    target_name = " ".join(str(args.get("target") or "").split()).strip()
    if not source_name or not target_name:
        return tool_error("folder (dossier actuel) et target (dossier de destination) obligatoires")
    try:
        uid = int(args.get("uid"))
    except (TypeError, ValueError):
        return tool_error("uid obligatoire (le numéro renvoyé par mail_scan)")
    force = bool(args.get("force"))
    if force:
        denied = _authorize("M0", operator_only=True)
        if denied:
            return tool_error(f"force réservé au propriétaire : {denied}")
    result, error = _file_one(source_name, uid, target_name, create=bool(args.get("create", True)), force=force)
    return tool_error(error) if error else tool_result(ok=True, **result)


def mail_file_supplier(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    source = " ".join(str(args.get("folder") or "").split()).strip()
    supplier = " ".join(str(args.get("supplier") or "").split()).strip()[:80]
    kind = " ".join(str(args.get("kind") or "").split()).strip()
    if not source:
        return tool_error("folder (dossier actuel du mail) obligatoire")
    if not supplier:
        return tool_error("supplier obligatoire")
    kinds = settings.supplier_kinds()
    if kinds and kind:
        match = next((item for item in kinds if item.casefold() == kind.casefold()), "")
        if not match:
            return tool_error(f"kind doit valoir : {', '.join(kinds)} (ou rester vide)")
        kind = match
    try:
        uid = int(args.get("uid"))
    except (TypeError, ValueError):
        return tool_error("uid obligatoire (le numéro renvoyé par mail_scan)")
    root = settings.folder_slot("suppliers", "Fournisseurs")
    target_name = f"{root}/{supplier}/{kind}" if kind else f"{root}/{supplier}"
    force = bool(args.get("force"))
    if force:
        denied = _authorize("M0", operator_only=True)
        if denied:
            return tool_error(f"force réservé au propriétaire : {denied}")
    result, error = _file_one(source, uid, target_name, create=True, force=force)
    return tool_error(error) if error else tool_result(ok=True, **result)


def mail_quarantine(args: dict, **_: Any) -> str:
    rec, error = _record(args.get("ref"))
    if error:
        return tool_error(error)
    protected = _protected_refusal(rec, "mettre en quarantaine")
    if protected:
        return tool_error(protected)
    reason = " ".join(str(args.get("reason") or "").split())[:300]
    if not reason:
        return tool_error("raison obligatoire")
    folder_name = settings.folder_slot("quarantine", "Suspects")
    fields: dict[str, Any] = {}
    moved = False
    if settings.live():
        try:
            with Mailbox(settings.imap_settings()) as mb:
                folders = mb.list_folders()
                dest = mb.resolve_folder(folder_name, folders)
                if dest is None:
                    mb.create_folder(imap_utf7.encode(folder_name), folders)
                    dest = mb.resolve_folder(folder_name)
                if dest is None:
                    return tool_error(f"dossier de quarantaine « {folder_name} » indisponible")
                source_raw, uid = _locate(mb, rec)
                if dest.raw != source_raw:
                    mb.move(uid, dest.raw)
                    moved = True
                fields = {"current_folder": dest.name, "current_folder_raw": dest.raw}
        except ImapError as exc:
            store().update(rec["ref"], last_error=str(exc))
            return tool_error(f"IMAP : {exc}")
    store().update(rec["ref"], suspect={"reason": reason, "at": time.time()}, status="suspect", **fields)
    return tool_result(ok=True, ref=rec["ref"], quarantaine=True, dossier=folder_name, deplace=moved,
                       raison=reason, note="Aucun brouillon ne sera préparé pour ce mail.")


# -- folder surgery (the owner's own conversation only) --------------------------------------------------------
def _folder_guard() -> Optional[str]:
    """Structure changes belong to the owner alone, and a shadow run must never restructure the mailbox."""
    denied = _authorize("M0", operator_only=True)
    if denied:
        return denied
    if not settings.live():
        return "mode shadow : la structure de la boîte n'est pas modifiée"
    return None


def _folder_raw(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Normalise a folder path typed by the agent and encode it to modified UTF-7.

    Control characters and IMAP quoting characters are refused outright instead of being scrubbed: a
    folder name is never multi-line, and quietly rewriting it would create a mailbox nobody asked for.
    ``INBOX`` itself is out of scope, but ``INBOX.<nom>`` is not: the server only accepts names inside
    that namespace, and the agent naturally sees its folders under that full name."""
    text = str(value or "")
    if any(ch in text for ch in '"\\\r\n\x00\t'):
        return None, "nom de dossier invalide (guillemets, antislash ou caractère de contrôle)"
    name = " ".join(text.split()).strip().strip(".")
    if not name:
        return None, "nom de dossier vide"
    if len(name) > 120:
        return None, "nom de dossier trop long (120 caractères maximum)"
    if name.upper() == "INBOX":
        return None, "INBOX lui-même est hors périmètre (ses sous-dossiers sont autorisés)"
    return imap_utf7.encode(name), None


_SYSTEM_FLAGS = frozenset({"\\drafts", "\\trash", "\\junk", "\\sent", "\\all", "\\archive", "\\flagged",
                           "\\important"})


def _protected(folder: Folder) -> Optional[str]:
    """Mailboxes the agent must never restructure: the account root and the provider's own.

    ``INBOX`` is the root of the whole hierarchy — only its sub-folders may be renamed or emptied,
    otherwise the mailbox could be detached from every folder it holds."""
    if folder.raw.upper() == "INBOX":
        return "INBOX lui-même est hors périmètre : seuls ses sous-dossiers peuvent être modifiés"
    system = sorted(folder.flags & _SYSTEM_FLAGS)
    return f"dossier système protégé ({', '.join(system)}) : ni renommage ni fusion" if system else None


def _hold_raw(folder: Folder) -> str:
    """``hold -<nom>`` applied to the last path segment: the parked name for a folder that ran empty.

    The parent path survives, so ``INBOX.Clients.2025`` becomes ``INBOX.Clients.hold -2025`` and the
    sibling folders are untouched."""
    delim = folder.delimiter or ""
    head, sep, tail = folder.raw.rpartition(delim) if delim else ("", "", folder.raw)
    return imap_utf7.encode(f"{head}{sep}hold -{imap_utf7.decode(tail)}")


def mail_folder_create(args: dict, **_: Any) -> str:
    denied = _folder_guard()
    if denied:
        return tool_error(denied)
    raw, error = _folder_raw(args.get("folder"))
    if error:
        return tool_error(error)
    try:
        with Mailbox(settings.imap_settings()) as mb:
            folders = mb.list_folders()
            existed = mb.resolve_folder(imap_utf7.decode(raw), folders) is not None
            created = mb.create_folder(raw, folders)
            after = mb.list_folders()
            found = mb.resolve_folder(imap_utf7.decode(raw), after)
    except ImapError as exc:
        return tool_error(f"IMAP : {exc}")
    if found is None:
        return tool_error(f"dossier « {imap_utf7.decode(raw)} » introuvable après CREATE")
    return tool_result(ok=True, folder=found.name, raw=found.raw,
                       crees=[imap_utf7.decode(item) for item in created], existait_deja=existed)


def mail_folder_rename(args: dict, **_: Any) -> str:
    denied = _folder_guard()
    if denied:
        return tool_error(denied)
    current = " ".join(str(args.get("folder") or "").split()).strip()
    new_raw, error = _folder_raw(args.get("new_name"))
    if error:
        return tool_error(error)
    try:
        with Mailbox(settings.imap_settings()) as mb:
            folders = mb.list_folders()
            source = mb.resolve_folder(current, folders)
            if source is None:
                return tool_error(f"dossier « {current} » introuvable")
            guarded = _protected(source)
            if guarded:
                return tool_error(guarded)
            if mb.resolve_folder(imap_utf7.decode(new_raw), folders) is not None:
                return tool_error(f"un dossier s'appelle déjà « {imap_utf7.decode(new_raw)} »")
            before = {f.raw for f in folders}
            mb.rename_folder(source.raw, new_raw, folders)
            after = mb.list_folders()
            followed = [f.name for f in after if f.raw not in before]
            landed = mb.resolve_folder(imap_utf7.decode(new_raw), after)
    except ImapError as exc:
        return tool_error(f"IMAP : {exc}")
    return tool_result(ok=True, renomme_de=source.name, vers=landed.name if landed else imap_utf7.decode(new_raw),
                       sous_dossiers_suivis=[name for name in followed if name != (landed.name if landed else "")],
                       note="Aucune suppression de dossier n'est possible par l'agent.")


def mail_folder_merge(args: dict, **_: Any) -> str:
    denied = _folder_guard()
    if denied:
        return tool_error(denied)
    src_name = " ".join(str(args.get("source") or "").split()).strip()
    dst_name = " ".join(str(args.get("target") or "").split()).strip()
    if not src_name or not dst_name:
        return tool_error("source et target obligatoires")
    hold_if_empty = bool(args.get("hold_if_empty"))
    try:
        with Mailbox(settings.imap_settings()) as mb:
            folders = mb.list_folders()
            source = mb.resolve_folder(src_name, folders)
            target = mb.resolve_folder(dst_name, folders)
            if source is None:
                return tool_error(f"dossier source « {src_name} » introuvable")
            if target is None:
                return tool_error(f"dossier cible « {dst_name} » introuvable (crée-le avec mail_folder_create)")
            if source.raw == target.raw:
                return tool_error("source et cible identiques")
            guarded = _protected(source)
            if guarded:
                return tool_error(guarded)
            mb.select(source.raw, readonly=False)
            pending = mb.uids_after(0)
            moved = mb.move_many(pending, target.raw) if pending else 0
            mb.select(source.raw, readonly=False)
            left = len(mb.uids_after(0))
            parked = None
            if hold_if_empty and left == 0:
                parked_raw = _hold_raw(source)
                mb.rename_folder(source.raw, parked_raw, folders)
                parked = imap_utf7.decode(parked_raw)
    except ImapError as exc:
        return tool_error(f"IMAP : {exc}")
    return tool_result(ok=True, source=source.name, target=target.name, deplaces=moved, restants=left,
                       parque=parked, note="Aucune suppression : un dossier vidé se renomme « hold -<nom> ».")


def mail_folder_info(args: dict, **_: Any) -> str:
    platform, _chat = _surface()
    if platform != settings.PLATFORM and platform not in _OPERATOR_SURFACES:
        return tool_error(f"surface non autorisée : {platform or 'inconnue'}")
    wanted = " ".join(str(args.get("folder") or "").split()).strip()
    try:
        with Mailbox(settings.imap_settings()) as mb:
            folders = mb.list_folders()
            if wanted:
                folder = mb.resolve_folder(wanted, folders)
                if folder is None:
                    return tool_error(f"dossier « {wanted} » introuvable")
                counts = mb.folder_status(folder.raw)
                total = counts.get("messages", 0)
                return tool_result(folder=folder.name, raw=folder.raw, messages=total,
                                   unseen=counts.get("unseen", 0), vide=total == 0,
                                   protege=bool(folder.flags & _SYSTEM_FLAGS),
                                   convention="un dossier vide se renomme « hold -<nom> », jamais supprimé")
            rows = []
            for folder in folders:
                if "\\noselect" in folder.flags or folder.raw.upper() == "INBOX":
                    continue
                counts = mb.folder_status(folder.raw)
                rows.append({"folder": folder.name, "messages": counts.get("messages", 0),
                             "unseen": counts.get("unseen", 0),
                             "protege": bool(folder.flags & _SYSTEM_FLAGS)})
    except ImapError as exc:
        return tool_error(f"IMAP : {exc}")
    rows.sort(key=lambda row: row["folder"].casefold())
    return tool_result(dossiers=rows, total=len(rows),
                       vides=[row["folder"] for row in rows if row["messages"] == 0 and not row["protege"]],
                       proteges=[row["folder"] for row in rows if row["protege"]],
                       parques=[row["folder"] for row in rows if row["folder"].startswith("hold -")],
                       convention="un dossier vide se renomme « hold -<nom> » ; la suppression reste manuelle (propriétaire)")


# -- schemas --------------------------------------------------------------------------------------------
_REF = {"type": "string", "description": "Référence du mail, ex. M1234"}


def _schema(name: str, description: str, properties: dict, required: tuple) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)}}


TOOLS = (
    (mail_get, _schema("mail_get", "Relire un mail suivi (en-têtes, corps, décision et brouillon actuels).",
                       {"ref": _REF}, ("ref",))),
    (mail_triage, _schema(
        "mail_triage",
        "Classer un mail : catégorie (dossier cible), marque, registre, priorité, besoin de réponse et résumé. "
        "En mode live, déplace le mail et le marque d'une étoile s'il faut répondre.",
        {"ref": _REF,
         "category": {"type": "string", "description": "Clé de catégorie configurée"},
         "needs_reply": {"type": "boolean"},
         "brand": {"type": "string", "enum": list(settings.brands())},
         "register": {"type": "string", "enum": list(settings.registers())},
         "priority": {"type": "string", "enum": list(settings.PRIORITIES)},
         "summary": {"type": "string", "description": "Résumé factuel en une ou deux phrases"},
         "supplier": {"type": "string", "description": "Catégorie fournisseurs : nom du dossier du fournisseur "
                      "(ex. « Grossiste Dupont »). Ignoré pour un fournisseur connu, reconnu par son domaine."},
         "supplier_kind": {"type": "string", "enum": list(settings.supplier_kinds()),
                           "description": "Type d'échange avec le fournisseur (vide = dossier du fournisseur)"}},
        ("ref", "category", "needs_reply", "brand", "register", "summary"))),
    (mail_save_draft, _schema(
        "mail_save_draft",
        "Enregistrer le brouillon de réponse dans le dossier Brouillons (remplace le brouillon précédent de ce mail). "
        "N'envoie jamais rien : le propriétaire valide et envoie lui-même.",
        {"ref": _REF, "body": {"type": "string", "description": "Texte de la réponse, sans la citation du mail"}},
        ("ref", "body"))),
    (mail_discard_draft, _schema(
        "mail_discard_draft", "Supprimer le brouillon préparé pour ce mail (uniquement sur demande du propriétaire).",
        {"ref": _REF}, ("ref",))),
    (mail_notify, _schema("mail_notify", "Signaler au propriétaire un mail important qui n'appelle pas de réponse.",
                          {"ref": _REF, "reason": {"type": "string"}}, ("ref", "reason"))),
    (mail_folders, _schema("mail_folders", "Lister les catégories configurées et les dossiers du serveur.", {}, ())),
    (mail_folder_create, _schema(
        "mail_folder_create",
        "Créer un dossier IMAP (les parents manquants sont créés et abonnés). Conversation avec le propriétaire uniquement.",
        {"folder": {"type": "string",
                    "description": "Chemin du dossier, ex. « Clients/2026 » ou « Clients.2026 »"}},
        ("folder",))),
    (mail_folder_rename, _schema(
        "mail_folder_rename",
        "Renommer un dossier IMAP (ses sous-dossiers suivent). Pour parquer un dossier devenu vide, préfixe "
        "son nom par « hold - ». Aucune suppression possible. Conversation avec le propriétaire uniquement.",
        {"folder": {"type": "string", "description": "Dossier actuel, nom exact ou court"},
         "new_name": {"type": "string", "description": "Nouveau nom, ex. « hold -Archive 2024 »"}},
        ("folder", "new_name"))),
    (mail_folder_merge, _schema(
        "mail_folder_merge",
        "Fusionner deux dossiers : déplacer TOUS les mails de « source » vers « target », puis avec "
        "hold_if_empty renommer la source vidée en « hold -<nom> ». Aucune suppression. Propriétaire uniquement.",
        {"source": {"type": "string", "description": "Dossier à vider"},
         "target": {"type": "string", "description": "Dossier qui reçoit les mails"},
         "hold_if_empty": {"type": "boolean",
                           "description": "Parquer la source si elle finit vide (préfixe « hold - »)"}},
        ("source", "target"))),
    (mail_folder_info, _schema(
        "mail_folder_info",
        "Compter les mails par dossier (un seul dossier si « folder » est donné) et repérer les dossiers vides, "
        "candidats à la convention « hold -<nom> ». Lecture seule.",
        {"folder": {"type": "string", "description": "Laisser vide pour balayer tous les dossiers"}}, ())),
    (mail_scan, _schema(
        "mail_scan",
        "Lister les mails d'un dossier — en-têtes seulement (uid, date, expéditeur, objet, lu), les plus "
        "récents d'abord. C'est le point de départ du rangement : le uid renvoyé sert ensuite à mail_move "
        "ou mail_file_supplier. Aucun corps de mail n'est téléchargé.",
        {"folder": {"type": "string", "description": "Dossier à parcourir, ex. « INBOX » ou « INBOX.Fournisseurs »"},
         "query": {"type": "string", "description": "Filtre sur l'expéditeur ou l'objet"},
         "limit": {"type": "integer", "description": "1 à 200, défaut 40"},
         "unseen_only": {"type": "boolean", "description": "Seulement les non lus"}}, ("folder",))),
    (mail_move, _schema(
        "mail_move",
        "Ranger UN mail précis (folder + uid, tels que renvoyés par mail_scan) dans un dossier de "
        "destination, créé au besoin. Un seul mail bouge, jamais un dossier entier. Un mail qui attend "
        "encore une réponse du propriétaire reste visible dans la boîte, sauf force=true depuis la conversation "
        "Telegram.",
        {"folder": {"type": "string", "description": "Dossier où le mail se trouve actuellement"},
         "uid": {"type": "integer", "description": "uid du mail, renvoyé par mail_scan"},
         "target": {"type": "string",
                    "description": "Destination, ex. « Fournisseurs/Dupont/Factures » ou « À traiter »"},
         "create": {"type": "boolean", "description": "Créer la destination si elle n'existe pas (défaut : oui)"},
         "force": {"type": "boolean", "description": "Ranger même un mail en attente de réponse (propriétaire uniquement)"}},
        ("folder", "uid", "target"))),
    (mail_file_supplier, _schema(
        "mail_file_supplier",
        "Ranger UN mail sous son fournisseur : « Fournisseurs/<fournisseur>/<type> », arborescence créée au "
        "besoin (parents compris). Types acceptés : échanges, commandes, factures, suivis — vide laisse le "
        "mail directement dans le dossier du fournisseur. Un seul mail bouge.",
        {"folder": {"type": "string", "description": "Dossier où le mail se trouve actuellement"},
         "uid": {"type": "integer", "description": "uid du mail, renvoyé par mail_scan"},
         "supplier": {"type": "string", "description": "Nom du fournisseur, ex. « Dupont Élec »"},
         "kind": {"type": "string", "enum": list(settings.supplier_kinds()),
                  "description": "Type d'échange (vide = dossier du fournisseur)"},
         "force": {"type": "boolean", "description": "Propriétaire uniquement"}},
        ("folder", "uid", "supplier"))),
    (mail_quarantine, _schema(
        "mail_quarantine",
        "Mettre un mail suivi à l'écart (message suspect, hameçonnage, incohérence) : il rejoint le dossier "
        "de quarantaine et plus aucun brouillon ne sera préparé pour lui.",
        {"ref": _REF, "reason": {"type": "string", "description": "Ce qui rend le mail suspect"}},
        ("ref", "reason"))),
    (mail_recent, _schema("mail_recent", "Lister les derniers mails suivis (conversation avec le propriétaire uniquement).",
                          {"limit": {"type": "integer"}, "pending_only": {"type": "boolean"}}, ())),
    (knowledge_search, _schema(
        "knowledge_search",
        "Chercher dans la base de connaissances du propriétaire (lecture seule) : services, procédures, "
        "conditions de vente, clients, fournisseurs, partenaires, projets. Requête en mots-clés.",
        {"query": {"type": "string"}, "limit": {"type": "integer", "description": "1 à 10, défaut 5"}}, ("query",))),
    (knowledge_read, _schema("knowledge_read", "Lire une page renvoyée par knowledge_search (chemin exact).",
                         {"path": {"type": "string"}}, ("path",))),
    (owner_fact_save, _schema(
        "owner_fact_save",
        "Enregistrer UN fait métier dicté par le propriétaire (horaires, tarif public, délai, procédure, condition…), utilisable "
        "aussitôt pour répondre aux mails. Reformule-le en une phrase claire et autonome. Conversation avec le propriétaire uniquement.",
        {"brand": {"type": "string", "enum": list(settings.fact_brands())},
         "topic": {"type": "string", "description": "Sujet court, ex. « Horaires boutique »"},
         "text": {"type": "string", "description": "Le fait, formulé pour être réutilisé tel quel"},
         "replaces": {"type": "string", "description": "Identifiant du fait remplacé (ex. F3), si c'est une mise à jour"}},
        ("brand", "topic", "text"))),
    (owner_fact_list, _schema("owner_fact_list", "Lister les faits enregistrés par le propriétaire.",
                             {"brand": {"type": "string", "enum": list(settings.fact_brands())}}, ())),
    (owner_fact_retire, _schema("owner_fact_retire", "Retirer un fait devenu faux (sur demande du propriétaire).",
                               {"id": {"type": "string"}}, ("id",))),
)
