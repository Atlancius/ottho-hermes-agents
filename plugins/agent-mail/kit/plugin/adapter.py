"""``mail_inbox`` gateway platform: IMAP IDLE on the pro mailbox, one agent session per new mail.

Flow: IDLE announces mail → fetch (BODY.PEEK, stays unread) → record → MessageEvent with the mail as untrusted
data and the triage procedure as ephemeral system prompt → the agent calls the ``mail_agent`` tools →
``on_processing_complete`` sends the owner a deterministic Telegram notification when a reply or attention is needed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType, ProcessingOutcome
from gateway.platforms.helpers import cancel_task

from . import notify, settings, tools
from .imap_client import AuthError, Mailbox
from .mailparse import parse_message, render_for_agent
from .store import valid_ref

logger = logging.getLogger(__name__)
_PENDING = ("queued", "dispatched", "processing")
_MAX_ATTEMPTS = 2
_BATCH = 20
_RESCUED_KEEP = 500  # Message-IDs remembered between the Junk rescue and the INBOX pickup


class MailInboxAdapter(BasePlatformAdapter):
    supports_async_delivery = False

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform(settings.PLATFORM))
        self._stop = threading.Event()
        self._mailbox: Optional[Mailbox] = None
        self._task: Optional[asyncio.Task] = None
        self._watchdog: Optional[asyncio.Task] = None
        self._slots: Optional[asyncio.Semaphore] = None
        self._inflight: Dict[str, float] = {}

    # -- lifecycle ------------------------------------------------------------------------------------
    async def connect(self, *, is_reconnect: bool = False) -> bool:
        creds = settings.imap_settings()
        if not (creds.address and creds.password):
            self._set_fatal_error("mail_agent_missing_configuration",
                                  "MAIL_AGENT_ADDRESS / MAIL_AGENT_PASSWORD absents du .env du profil", retryable=False)
            return False
        if not creds.host:
            self._set_fatal_error("mail_agent_missing_configuration",
                                  "imap.host absent de mail-agent.yaml (serveur IMAP du fournisseur)", retryable=False)
            return False
        try:
            await asyncio.to_thread(self._open)
        except AuthError as exc:
            self._set_fatal_error("mail_agent_auth", str(exc), retryable=False)
            return False
        except Exception as exc:
            self._set_fatal_error("mail_agent_connect", f"{type(exc).__name__}: {exc}", retryable=True)
            return False
        self._stop.clear()
        self._slots = asyncio.Semaphore(max(1, int(settings.config()["limits"]["max_concurrent"])))
        self._running = True
        self._task = asyncio.create_task(self._run(), name="mail-agent-idle")
        self._watchdog = asyncio.create_task(self._watch(), name="mail-agent-watchdog")
        self._mark_connected()
        logger.info("[mail-agent] connecté, mode %s", "live" if settings.live() else "shadow")
        return True

    async def disconnect(self) -> None:
        self._stop.set()
        self._running = False
        mailbox, self._mailbox = self._mailbox, None
        if mailbox:
            mailbox.abort()
        await cancel_task(self._task)
        await cancel_task(self._watchdog)
        self._task = self._watchdog = None
        if mailbox:
            await asyncio.to_thread(mailbox.close)
        self._mark_disconnected()

    def _open(self) -> None:
        """(thread) Connect, select INBOX read-only and set the watermark baseline on first run."""
        mailbox = Mailbox(settings.imap_settings())
        mailbox.connect()
        try:
            uidvalidity = mailbox.select(settings.config()["imap"]["inbox"], readonly=True)
            state = tools.store().state()
            if "watermark" not in state or state.get("uidvalidity") != uidvalidity:
                baseline = mailbox.max_uid()
                if "watermark" in state:
                    logger.warning("[mail-agent] UIDVALIDITY changé : nouveau point de départ UID %s", baseline)
                tools.store().save_state(uidvalidity=uidvalidity, watermark=baseline)
        except BaseException:
            mailbox.close()
            raise
        self._mailbox = mailbox

    # -- main loop ------------------------------------------------------------------------------------
    async def _run(self) -> None:
        await self._recover()
        backoff = 5.0
        while not self._stop.is_set():
            try:
                if self._mailbox is None:
                    await asyncio.to_thread(self._open)
                    self._mark_connected()
                if settings.live() and settings.junk_rescue():
                    await asyncio.to_thread(self._rescue_junk)
                refs = await asyncio.to_thread(self._collect)
                for ref in refs:
                    await self._dispatch(ref)
                backoff = 5.0
                if refs:
                    continue
                cycle = float(settings.config()["limits"]["idle_cycle_seconds"])
                await asyncio.to_thread(self._mailbox.idle, cycle)
            except asyncio.CancelledError:
                raise
            except AuthError as exc:
                self._set_fatal_error("mail_agent_auth", str(exc), retryable=False)
                await asyncio.to_thread(notify.send_owner, f"Agent mail arrêté : {exc}. Mets à jour le mot de passe.")
                await self._notify_fatal_error()
                return
            except Exception as exc:
                if self._stop.is_set():
                    return
                logger.warning("[mail-agent] IMAP interrompu (%s: %s), reprise dans %.0f s",
                               type(exc).__name__, exc, backoff)
                mailbox, self._mailbox = self._mailbox, None
                if mailbox:
                    await asyncio.to_thread(mailbox.close)
                self._write_runtime_status_safe("retrying", platform_state="retrying", error_code="mail_agent_imap",
                                                error_message=f"{type(exc).__name__}: {exc}"[:300])
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)

    def _collect(self) -> list[str]:
        """(thread) Fetch mail above the watermark into records; return refs to dispatch."""
        mailbox, store = self._mailbox, tools.store()
        cfg = settings.config()
        uidvalidity = mailbox.select(cfg["imap"]["inbox"], readonly=True)
        state = store.state()
        if state.get("uidvalidity") != uidvalidity:
            store.save_state(uidvalidity=uidvalidity, watermark=mailbox.max_uid())
            logger.warning("[mail-agent] UIDVALIDITY changé en cours de route : point de départ réinitialisé")
            return []
        refs = []
        own = settings.imap_settings().address
        for uid in mailbox.uids_after(int(state.get("watermark", 0)))[:_BATCH]:
            ref = f"M{uid}"
            raw = mailbox.fetch_raw(uid, int(cfg["limits"]["max_fetch_bytes"]))
            if raw is not None and store.get(ref) is None:
                rec = parse_message(raw, own_address=own, protected_domains=settings.protected_domains(),
                                    trusted_forwarders=settings.trusted_forwarders())
                known = store.find_by_message_id(rec["message_id"])
                if known is not None:
                    # Moved back into INBOX (by the owner or by a re-triage): same mail, new UID. Track, never reprocess.
                    inbox = cfg["imap"]["inbox"]
                    store.update(known["ref"], inbox_uid=uid, current_folder=inbox, current_folder_raw=inbox)
                    logger.info("[mail-agent] %s revenu dans la boîte (UID %s), pas de nouveau traitement",
                                known["ref"], uid)
                    store.save_state(watermark=uid)
                    continue
                rescued = list(store.state().get("junk_rescued") or [])
                if rec["message_id"] and rec["message_id"] in rescued:
                    rec["server_spam"] = True
                    rescued.remove(rec["message_id"])
                    store.save_state(junk_rescued=rescued)
                rec.update(ref=ref, inbox_uid=uid, uidvalidity=uidvalidity, received_at=time.time(), attempts=0,
                           mode="live" if settings.live() else "shadow",
                           status="skipped" if rec["from_self"] else "queued")
                store.put(rec)
                if rec["status"] == "queued":
                    refs.append(ref)
            store.save_state(watermark=uid)
        return refs

    def _rescue_junk(self) -> None:
        """(thread) The server's spam filter files mail straight into Junk, out of the agent's sight: a contact form
        from the owner's own site was lost that way. Every new arrival in Junk that the agent has not judged yet goes back
        to INBOX, where the normal triage gives its own verdict (true spam returns to Junk, never twice)."""
        mailbox, store = self._mailbox, tools.store()
        junk = next((f for f in mailbox.list_folders() if r"\junk" in f.flags), None)
        if junk is None:
            return
        inbox = settings.config()["imap"]["inbox"]
        uidvalidity = mailbox.select(junk.raw, readonly=False)
        state = store.state()
        if state.get("junk_uidvalidity") != uidvalidity or "junk_watermark" not in state:
            # First run (or Junk recreated): start from now, the backlog is the owner's call, never moved in bulk.
            store.save_state(junk_uidvalidity=uidvalidity, junk_watermark=mailbox.max_uid())
            logger.info("[mail-agent] surveillance de Junk activée, point de départ UID %s", mailbox.max_uid())
            return
        rescued = list(state.get("junk_rescued") or [])
        moved = 0
        for uid in mailbox.uids_after(int(state.get("junk_watermark", 0)))[:_BATCH]:
            message_id = mailbox.fetch_header_field(uid, "Message-ID").strip()
            if message_id and store.find_by_message_id(message_id) is None:
                mailbox.move(uid, inbox)
                rescued.append(message_id)
                moved += 1
            elif not message_id:
                logger.warning("[mail-agent] Junk UID %s sans Message-ID : laissé en place (anti-boucle)", uid)
            store.save_state(junk_watermark=uid, junk_rescued=rescued[-_RESCUED_KEEP:])
        if moved:
            logger.info("[mail-agent] %d mail(s) remis de Junk dans la réception pour tri par l'agent", moved)

    async def _recover(self) -> None:
        """Re-dispatch mail left pending by a previous process (crash, restart) once, then give up loudly."""
        pending = sorted((r for r in tools.store().all() if r.get("status") in _PENDING),
                         key=lambda r: int(r.get("inbox_uid", 0)))
        for rec in pending:
            if int(rec.get("attempts", 0)) >= _MAX_ATTEMPTS:
                await self._fail(rec["ref"], "abandonné après redémarrages successifs")
            else:
                await self._dispatch(rec["ref"])

    # -- dispatch ---------------------------------------------------------------------------------------
    async def _dispatch(self, ref: str) -> None:
        await self._slots.acquire()
        self._inflight[ref] = time.monotonic()
        store = tools.store()
        rec = store.update(ref, status="dispatched", dispatched_at=time.time(),
                           attempts=int((store.get(ref) or {}).get("attempts", 0)) + 1)
        text = render_for_agent(ref, rec, body_chars=int(settings.config()["limits"]["body_chars"]))
        source = self.build_source(chat_id=f"mail:{ref}", chat_name=f"Mail {ref}", chat_type="dm",
                                   user_id=settings.WATCHER_USER, user_name="Boîte mail", message_id=ref)
        event = MessageEvent(text=text, message_type=MessageType.TEXT, user_id=settings.WATCHER_USER,
                             user_name="Boîte mail", source=source, message_id=ref,
                             channel_prompt=settings.mail_procedure(), allow_gateway_control=False,
                             metadata={"mail_agent_ref": ref})
        try:
            await self.handle_message(event)
        except Exception as exc:
            await self._fail(ref, f"dispatch impossible : {type(exc).__name__}: {exc}")
            return
        if not event._gateway_accepted:
            await self._fail(ref, "refusé par la gateway (autorisation ou file de session)")

    def _release(self, ref: str) -> bool:
        if self._inflight.pop(ref, None) is None:
            return False
        if self._slots is not None:
            self._slots.release()
        return True

    async def _fail(self, ref: str, reason: str) -> None:
        self._release(ref)
        try:
            rec = tools.store().update(ref, status="failed", last_error=reason)
        except KeyError:
            return
        logger.error("[mail-agent] %s en échec : %s", ref, reason)
        await asyncio.to_thread(notify.send_owner, notify.compose_failure(rec, reason))

    def toolsets_for_source(self, source) -> Optional[list]:
        return [settings.TOOLSET]

    async def on_processing_start(self, event: MessageEvent) -> None:
        ref = (event.metadata or {}).get("mail_agent_ref")
        if ref:
            tools.store().update(ref, status="processing")

    async def on_processing_complete(self, event: MessageEvent, outcome: ProcessingOutcome) -> None:
        ref = (event.metadata or {}).get("mail_agent_ref")
        if not ref or not self._release(ref):
            return  # already settled by the watchdog
        store = tools.store()
        if outcome == ProcessingOutcome.SUCCESS:
            rec = store.update(ref, status="done" if (store.get(ref) or {}).get("decision") else "untriaged",
                               completed_at=time.time())
            if notify.should_notify(rec):
                sent = await asyncio.to_thread(notify.send_owner, notify.compose(rec))
                store.update(ref, notified=sent)
        else:
            reason = "traitement annulé" if outcome == ProcessingOutcome.CANCELLED else (
                (store.get(ref) or {}).get("last_error") or "erreur pendant le traitement de l'agent")
            await self._fail(ref, reason)  # slot already released above; _release is idempotent

    async def _watch(self) -> None:
        last_prune = 0.0
        while not self._stop.is_set():
            await asyncio.sleep(60)
            limit = float(settings.config()["limits"]["watchdog_minutes"]) * 60
            now = time.monotonic()
            for ref, started in list(self._inflight.items()):
                if now - started > limit:
                    await self._fail(ref, f"aucune fin de traitement après {limit / 60:.0f} min")
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                removed = await asyncio.to_thread(tools.store().prune,
                                                  float(settings.config()["limits"]["retention_days"]))
                if removed:
                    logger.info("[mail-agent] %d fiches de plus de la rétention supprimées", removed)

    # -- outbound ---------------------------------------------------------------------------------------
    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> SendResult:
        """Agent output for a mail session becomes the note shown in the notification; anything else
        addressed to this platform (cron delivery…) is relayed to the owner."""
        if chat_id.startswith("mail:"):
            ref = chat_id[5:]
            if valid_ref(ref) and tools.store().get(ref) is not None:
                tools.store().update(ref, agent_note=(content or "")[:4000])
            return SendResult(success=True, message_id=f"{ref}-note")
        ok = await asyncio.to_thread(notify.send_owner, content or "")
        return SendResult(success=ok, error=None if ok else "notification Telegram en échec")

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": chat_id, "type": "dm", "chat_id": chat_id}
