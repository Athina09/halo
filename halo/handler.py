import logging
import re
from collections import defaultdict
from threading import Lock

from .agent import Agent
from .db import Store
from .fallback import Fallback, text_payload
from .keyward import Keyward, KeywardError

log = logging.getLogger("halo.handler")

MAX_REPLY_CHARS = 1000
CALL_COMMAND = re.compile(r"^\s*call\s+#?(\d{1,9})\s*$", re.IGNORECASE)


def make_sender(phone_number_id: str, keyward: Keyward):
    def send(phone: str, key: str, payloads: list[dict]) -> None:
        p = keyward.new_pass(f"msg-{key}", ["whatsapp"], uses=len(payloads) + 1)  # fresh pass per message
        try:
            for payload in payloads:
                keyward.send_whatsapp(p, phone_number_id, {"to": phone, **payload})
        finally:
            keyward.drop_pass(p)
    return send


def make_notifier(phone_number_id: str, keyward: Keyward):
    send = make_sender(phone_number_id, keyward)
    return lambda phone, key, text: send(phone, key, [text_payload(text[:MAX_REPLY_CHARS])])


def make_handler(phone_number_id: str, keyward: Keyward, agent: Agent, fallback: Fallback, store: Store,
                 owner: str = "", start_call=None):
    locks: defaultdict[str, Lock] = defaultdict(Lock)  # one message at a time per person
    send = make_sender(phone_number_id, keyward)

    def handle(m: dict) -> None:
        phone = m["from"]
        with locks[phone]:
            call_cmd = CALL_COMMAND.match(m["text"]) if start_call and owner and phone == owner else None
            if call_cmd:  # only the owner can start a call; the model never can
                payloads = [text_payload(start_call(int(call_cmd.group(1))))]
            elif store.get_mode(phone) == "buttons":
                payloads = fallback.handle(m)
            elif not m["text"]:
                payloads = [text_payload("I can only read text messages for now.")]
            else:
                reply = agent.reply(phone, m["text"])
                if reply is None:
                    store.set_mode(phone, "buttons")
                    payloads = fallback.handle(m, switched=True)
                else:
                    payloads = [text_payload(reply[:MAX_REPLY_CHARS])]
            try:
                send(phone, m["id"], payloads)
            except KeywardError as e:
                log.warning("could not send reply for %s: %s", m["id"], e)

    return handle
