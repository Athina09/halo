"""Chat with Halo in the terminal, no WhatsApp or Meta account needed.

    .venv/bin/python -m sim.chat              # uses your local Ollama if it is running
    .venv/bin/python -m sim.chat --no-ollama  # pretend Ollama is down: see the button flow

Halo runs for real (webhook, allowlist, agent loop, buttons, SQLite). Only the outside world is
faked: Keyward says every webhook is genuine, and "WhatsApp" is your terminal.
"""
import argparse
import json
import os
import tempfile

import httpx
from fastapi.testclient import TestClient

from halo.config import Settings
from halo.db import Store
from halo.keyward import Keyward
from halo.main import create_app
from halo.ollama import Ollama

PHONE = "919876543210"


def render(payload: dict) -> tuple[str, list[tuple[str, str]]]:
    """(text to show, [(id, title)] the user can tap) for one outgoing WhatsApp payload."""
    if payload.get("type") == "text":
        return payload["text"]["body"], []
    i = payload["interactive"]
    if i["type"] == "button":
        return i["body"]["text"], [(b["reply"]["id"], b["reply"]["title"]) for b in i["action"]["buttons"]]
    rows = i["action"]["sections"][0]["rows"]
    return i["body"]["text"], [(r["id"], r["title"] + (f" ({r['description']})" if r.get("description") else ""))
                               for r in rows]


class Sim:
    def __init__(self, ollama, db_path: str, phone: str = PHONE):
        self.phone, self.sent, self._n = phone, [], 0
        settings = Settings("http://kw", "sim", "123", "sim-verify", phone, (), db_path, "http://ol", "sim", 20)
        keyward = Keyward("http://kw", "sim", client=httpx.Client(transport=httpx.MockTransport(self._fake_keyward)))
        self.store = Store(db_path)
        self.client = TestClient(create_app(settings, keyward, ollama, self.store))

    def _fake_keyward(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/health":
            return httpx.Response(200, json={"ok": True, "frozen": False})
        if path == "/passes":
            return httpx.Response(200, json={"pass": "sim-pass"})
        if path.startswith("/verify/"):
            return httpx.Response(200, json={"valid": True})
        if path.startswith("/channels/"):
            return httpx.Response(200, json={"handled": False})
        if path.startswith("/use/whatsapp/"):
            self.sent.append(json.loads(req.content))
        return httpx.Response(200, json={})

    def _post(self, message: dict) -> list[dict]:
        self._n += 1
        body = {"entry": [{"changes": [{"value": {"messages": [
            {"id": f"wamid.sim{self._n}", "from": self.phone, **message}]}}]}]}
        self.sent = []
        r = self.client.post("/webhook", content=json.dumps(body), headers={"x-hub-signature-256": "sha256=sim"})
        assert r.status_code == 200, r.text
        return self.sent  # replies are sent before the request returns

    def say(self, text: str) -> list[dict]:
        return self._post({"type": "text", "text": {"body": text}})

    def tap(self, reply_id: str, title: str = "") -> list[dict]:
        return self._post({"type": "interactive", "interactive": {"button_reply": {"id": reply_id, "title": title}}})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-ollama", action="store_true", help="pretend Ollama is down (button flow only)")
    ap.add_argument("--db", help="SQLite file to keep between runs (default: a temporary one)")
    args = ap.parse_args()
    url = "http://127.0.0.1:1" if args.no_ollama else os.environ.get("OLLAMA_URL", "http://localhost:11434")
    llm = Ollama(url, os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"), float(os.environ.get("OLLAMA_TIMEOUT", "20")))
    sim = Sim(llm, args.db or os.path.join(tempfile.mkdtemp(), "sim.db"))
    print("Ollama:", "reachable, the assistant will answer" if llm.reachable() else "NOT reachable, buttons only")
    print("Type a message. When options are shown, type their number. Ctrl-D to quit.\n")

    options: list[tuple[str, str]] = []
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if options and line.isdigit() and 1 <= int(line) <= len(options):
            rid, title = options[int(line) - 1]
            out = sim.tap(rid, title)
        else:
            out = sim.say(line)
        options = []
        for payload in out:
            text, opts = render(payload)
            print(f"halo> {text}")
            for n, (_, title) in enumerate(opts, 1):
                print(f"        [{n}] {title}")
            options = opts or options
        if not out:
            print("halo> (no reply)")


if __name__ == "__main__":
    main()
