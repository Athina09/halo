"""The agent loop: our code decides what runs, the model only asks."""
import json
import logging
from collections.abc import Callable
from datetime import datetime

from .db import Store
from .ollama import Ollama, OllamaError
from .tools import IST, TOOL_NAMES, TOOLS, run_tool

log = logging.getLogger("halo.agent")

MAX_ROUNDS = 4
MAX_INVALID = 2
MAX_USER_CHARS = 1000

SYSTEM = """You are Halo, a WhatsApp assistant that takes restaurant table requests. Nothing else.
Now: {now} (Asia/Kolkata). Work out dates like "tomorrow" or "Friday" from this.
Rules:
- Reply in the user's own language (English, Tamil, Hindi or mixed). Keep replies short, WhatsApp style.
- To make a request you need: restaurant, date, time, number of people (1-20) and a name. Ask for what is missing, one thing at a time.
- When you have everything, call save_booking_request. Never guess missing details.
- You only SAVE REQUESTS. Never say a table is booked or confirmed; say the request is saved and will be confirmed separately.
- Use listings to show their requests and cancel_booking to cancel one.
- If asked for anything unrelated to table requests, politely say you can only help with that."""


def system_prompt(now: datetime) -> str:
    return SYSTEM.format(now=now.strftime("%A %Y-%m-%d %H:%M"))


class Agent:
    def __init__(self, ollama: Ollama, store: Store, now: Callable[[], datetime] | None = None):
        self._llm, self._store = ollama, store
        self._now = now or (lambda: datetime.now(IST))

    def reply(self, phone: str, text: str) -> str | None:
        """Final reply text, or None when this person should be switched to the button flow."""
        now = self._now()
        text = text.strip()[:MAX_USER_CHARS]
        messages = [{"role": "system", "content": system_prompt(now)}]
        messages += self._store.history(phone, 20)
        messages.append({"role": "user", "content": text})
        self._store.add_message(phone, "user", text)

        invalid = 0
        for _ in range(MAX_ROUNDS):
            try:
                msg = self._llm.chat(messages, TOOLS)
            except OllamaError as e:
                log.warning("ollama %s: %s", e.kind, e)
                if e.kind != "invalid":
                    return None
                invalid += 1
                if invalid >= MAX_INVALID:
                    return None
                continue

            calls = msg["tool_calls"]
            if not calls:
                content = msg["content"].strip()
                if content:
                    self._store.add_message(phone, "assistant", content)
                    return content
                invalid += 1
                if invalid >= MAX_INVALID:
                    return None
                continue

            messages.append({"role": "assistant", "content": msg["content"], "tool_calls": calls})
            for call in calls:
                name, args = _parse_call(call)
                if name is None:
                    invalid += 1
                    result = {"error": "invalid tool call. Use one of: " + ", ".join(sorted(TOOL_NAMES))}
                else:
                    result = run_tool(self._store, phone, name, args, now)
                messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})
            if invalid >= MAX_INVALID:
                return None
        log.warning("no final reply after %d rounds", MAX_ROUNDS)
        return None


def _parse_call(call) -> tuple[str | None, dict]:
    """(tool name, args) for a well-formed request for a tool we know, else (None, {})."""
    try:
        fn = call["function"]
        name, args = fn["name"], fn.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)
    except (KeyError, TypeError, ValueError):
        return None, {}
    if name not in TOOL_NAMES or not isinstance(args, dict):
        return None, {}
    return name, args
