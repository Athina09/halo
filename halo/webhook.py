import hmac
import logging
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from .config import Settings
from .db import Store
from .keyward import Keyward, KeywardError

log = logging.getLogger("halo.webhook")

Message = dict  # {"id", "from", "type", "text", "reply_id"}
Handler = Callable[[Message], None]


def parse_messages(payload: dict) -> list[Message]:
    """Pull user messages out of a WhatsApp webhook body. Delivery receipts yield nothing."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for m in (change.get("value") or {}).get("messages") or []:
                if not isinstance(m, dict) or not m.get("id") or not m.get("from"):
                    continue
                text, reply_id = "", ""
                if m.get("type") == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif m.get("type") == "interactive":
                    i = m.get("interactive") or {}
                    r = i.get("button_reply") or i.get("list_reply") or {}
                    text, reply_id = r.get("title", ""), r.get("id", "")
                out.append({"id": m["id"], "from": m["from"], "type": m.get("type", ""),
                            "text": text, "reply_id": reply_id})
    return out


def build_router(settings: Settings, keyward: Keyward, store: Store, handler: Handler) -> APIRouter:
    router = APIRouter()
    allowed = set(settings.allowed_numbers) | {settings.owner_number}
    allowed.discard("")

    @router.get("/webhook")
    def verify(mode: str = Query("", alias="hub.mode"),
               token: str = Query("", alias="hub.verify_token"),
               challenge: str = Query("", alias="hub.challenge")):
        ok = (mode == "subscribe" and settings.whatsapp_verify_token
              and hmac.compare_digest(token, settings.whatsapp_verify_token))
        if not ok:
            return Response(status_code=403)
        return PlainTextResponse(challenge)

    @router.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks):
        raw = await request.body()
        sig = request.headers.get("x-hub-signature-256", "")
        try:
            # Is this really from WhatsApp? Halo never holds the app secret.
            if not await run_in_threadpool(keyward.verify_whatsapp, raw, sig):
                return Response(status_code=403)
            payload = await request.json()
            messages = parse_messages(payload) if isinstance(payload, dict) else []
            # Owner commands (YES 123456, FREEZE...) go to Keyward untouched.
            if any(m["from"] == settings.owner_number for m in messages):
                if await run_in_threadpool(keyward.forward_inbound, raw, sig):
                    return {"ok": True}
        except KeywardError as e:
            log.warning("keyward unavailable: %s", e)
            return Response(status_code=503)  # WhatsApp will retry
        except ValueError:
            return {"ok": True}  # signed but not JSON: nothing to do

        for m in messages:
            if m["from"] not in allowed:
                log.info("ignored message %s from a number not on the allowlist", m["id"])
                continue
            if not await run_in_threadpool(store.first_time, m["id"]):
                continue  # WhatsApp retry
            background.add_task(_safe, handler, m)
        return {"ok": True}

    return router


def _safe(handler: Handler, message: Message) -> None:
    try:
        handler(message)
    except Exception:
        log.exception("failed to process message %s", message.get("id"))
