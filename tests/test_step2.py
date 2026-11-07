import json

import httpx
import pytest
from fastapi.testclient import TestClient

from halo.config import Settings
from halo.db import Store
from halo.keyward import Keyward
from halo.main import create_app
from halo.ollama import Ollama

OWNER, FRIEND, STRANGER = "919876543210", "919000000001", "918888888888"


def body(sender, mid="wamid.1", text="table for 4"):
    msg = {"id": mid, "from": sender, "type": "text", "text": {"body": text}}
    return json.dumps({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()


class Env:
    def __init__(self, tmp_path, valid=True, handled=False, kw_down=False):
        self.calls, self.got = [], []
        self.valid, self.handled, self.kw_down = valid, handled, kw_down
        s = Settings("http://kw", "tok", "123", "vt", OWNER, (FRIEND,), str(tmp_path / "h.db"),
                     "http://ol", "m", 20)
        kw = Keyward("http://kw", "tok", client=httpx.Client(transport=httpx.MockTransport(self._kw)))
        ol = Ollama("http://ol", "m", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
        self.client = TestClient(create_app(s, kw, ol, Store(s.db_path), self.got.append))

    def _kw(self, req):
        self.calls.append(req.url.path)
        if self.kw_down:
            raise httpx.ConnectError("down")
        if req.url.path == "/verify/whatsapp":
            return httpx.Response(200, json={"valid": self.valid})
        return httpx.Response(200, json={"handled": self.handled})

    def post(self, raw, sig="sha256=ab"):
        return self.client.post("/webhook", content=raw, headers={"x-hub-signature-256": sig})


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_verify_handshake(env):
    r = env.client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "123"})
    assert r.status_code == 200 and r.text == "123"


@pytest.mark.parametrize("params", [
    {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    {"hub.mode": "unsubscribe", "hub.verify_token": "vt", "hub.challenge": "1"},
    {},
])
def test_verify_handshake_rejects(env, params):
    assert env.client.get("/webhook", params=params).status_code == 403


def test_bad_signature_is_403_and_nothing_processed(tmp_path):
    e = Env(tmp_path, valid=False)
    assert e.post(body(OWNER)).status_code == 403
    assert e.got == [] and e.calls == ["/verify/whatsapp"]


def test_friend_message_is_processed_not_forwarded_to_keyward(env):
    assert env.post(body(FRIEND)).status_code == 200
    assert [m["text"] for m in env.got] == ["table for 4"]
    assert "/channels/whatsapp/inbound" not in env.calls


def test_owner_message_is_forwarded_and_processed_when_not_a_command(env):
    env.post(body(OWNER))
    assert "/channels/whatsapp/inbound" in env.calls and len(env.got) == 1


def test_owner_command_handled_by_keyward_is_not_processed(tmp_path):
    e = Env(tmp_path, handled=True)
    e.post(body(OWNER, text="YES 123456"))
    assert e.got == []


def test_stranger_is_ignored(env):
    assert env.post(body(STRANGER)).status_code == 200
    assert env.got == []


def test_duplicate_delivery_is_processed_once(env):
    env.post(body(FRIEND, mid="wamid.same"))
    env.post(body(FRIEND, mid="wamid.same"))
    assert len(env.got) == 1


def test_status_updates_are_ignored(env):
    raw = json.dumps({"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}).encode()
    assert env.post(raw).status_code == 200 and env.got == []


def test_interactive_reply_is_parsed(env):
    msg = {"id": "w2", "from": FRIEND, "type": "interactive",
           "interactive": {"button_reply": {"id": "confirm", "title": "Confirm"}}}
    raw = json.dumps({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()
    env.post(raw)
    assert env.got[0]["reply_id"] == "confirm"


def test_keyward_down_returns_503_so_whatsapp_retries(tmp_path):
    e = Env(tmp_path, kw_down=True)
    assert e.post(body(FRIEND)).status_code == 503 and e.got == []


def test_handler_crash_does_not_break_webhook(tmp_path):
    e = Env(tmp_path)
    e.client.app.router.routes  # app built; swap handler via new env below
    s = Settings("http://kw", "tok", "123", "vt", OWNER, (FRIEND,), str(tmp_path / "c.db"), "http://ol", "m", 20)
    kw = Keyward("http://kw", "tok", client=httpx.Client(transport=httpx.MockTransport(e._kw)))
    def boom(m): raise RuntimeError("x")
    app = create_app(s, kw, None, Store(s.db_path), boom)
    r = TestClient(app).post("/webhook", content=body(FRIEND), headers={"x-hub-signature-256": "s"})
    assert r.status_code == 200
