import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from halo.config import Settings
from halo.keyward import Keyward, KeywardError
from halo.main import create_app
from halo.ollama import Ollama, OllamaError

SETTINGS = Settings("http://kw", "kw_tok", "123", "vt", "919876543210", (), ":memory:", "http://ol", "m", 20)


def fake_ollama(handler) -> Ollama:
    return Ollama("http://ol", "m", 20, client=httpx.Client(transport=httpx.MockTransport(handler)))


def fake_keyward(handler) -> Keyward:
    return Keyward("http://kw", "kw_tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


# ---- Ollama client -------------------------------------------------------

def test_chat_returns_message_and_sends_tools():
    seen = {}

    def handler(req):
        seen.update(httpx.Response(200, content=req.content).json())
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi"}})

    msg = fake_ollama(handler).chat([{"role": "user", "content": "hello"}], tools=[{"type": "function"}])
    assert msg["content"] == "hi" and msg["tool_calls"] == []
    assert seen["stream"] is False and seen["model"] == "m" and seen["tools"]


def test_chat_returns_tool_calls():
    call = {"function": {"name": "save_booking_request", "arguments": {"people": 4}}}
    msg = fake_ollama(lambda r: httpx.Response(200, json={"message": {"content": "", "tool_calls": [call]}})).chat([])
    assert msg["tool_calls"] == [call]


def test_chat_timeout_is_ollama_error():
    def handler(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(OllamaError, match="timed out"):
        fake_ollama(handler).chat([])


def test_chat_down_is_ollama_error():
    def handler(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(OllamaError):
        fake_ollama(handler).chat([])


@pytest.mark.parametrize("body", [{"nope": 1}, {"message": "text"}, {"message": None}])
def test_chat_invalid_reply_is_ollama_error(body):
    with pytest.raises(OllamaError):
        fake_ollama(lambda r: httpx.Response(200, json=body)).chat([])


def test_chat_non_json_is_ollama_error():
    with pytest.raises(OllamaError):
        fake_ollama(lambda r: httpx.Response(200, content=b"<html>")).chat([])


def test_reachable():
    assert fake_ollama(lambda r: httpx.Response(200, json={"models": []})).reachable() is True

    def down(req):
        raise httpx.ConnectError("refused")

    assert fake_ollama(down).reachable() is False


# ---- Keyward client ------------------------------------------------------

def test_new_pass_returns_header_and_sends_agent_token():
    seen = {}

    def handler(req):
        seen["agent"] = req.headers["x-keyward-agent"]
        seen["body"] = httpx.Response(200, content=req.content).json()
        return httpx.Response(200, json={"pass": "kwp_abc"})

    p = fake_keyward(handler).new_pass("msg-1", ["whatsapp"])
    assert p == {"x-keyward-pass": "kwp_abc"}
    assert seen["agent"] == "kw_tok"
    assert seen["body"]["routes"] == ["whatsapp"] and seen["body"]["subject"] == "msg-1"


def test_new_pass_failure_is_keyward_error():
    with pytest.raises(KeywardError):
        fake_keyward(lambda r: httpx.Response(401)).new_pass("x", ["whatsapp"])


def test_verify_and_inbound_send_raw_body_base64():
    seen = []

    def handler(req):
        seen.append((req.url.path, httpx.Response(200, content=req.content).json()))
        return httpx.Response(200, json={"valid": True, "handled": False})

    kw = fake_keyward(handler)
    assert kw.verify_whatsapp(b'{"a":1}', "sha256=ff") is True
    assert kw.forward_inbound(b'{"a":1}', "sha256=ff") is False
    assert seen[0][0] == "/verify/whatsapp" and seen[1][0] == "/channels/whatsapp/inbound"
    assert base64.b64decode(seen[0][1]["payload_b64"]) == b'{"a":1}'
    assert seen[0][1]["signature"] == "sha256=ff"


def test_send_whatsapp_goes_through_use_route_with_pass_only():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["headers"] = dict(req.headers)
        seen["body"] = httpx.Response(200, content=req.content).json()
        return httpx.Response(200, json={})

    fake_keyward(handler).send_whatsapp(
        {"x-keyward-pass": "kwp_abc"}, "123", {"to": "91", "type": "text", "text": {"body": "hi"}}
    )
    assert seen["path"] == "/use/whatsapp/v21.0/123/messages"
    assert seen["headers"]["x-keyward-pass"] == "kwp_abc"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["messaging_product"] == "whatsapp"


def test_healthy():
    assert fake_keyward(lambda r: httpx.Response(200, json={"ok": True, "frozen": False})).healthy() is True

    def down(req):
        raise httpx.ConnectError("refused")

    assert fake_keyward(down).healthy() is False


# ---- /health -------------------------------------------------------------

def test_health_reports_both_up():
    app = create_app(
        SETTINGS,
        fake_keyward(lambda r: httpx.Response(200, json={"ok": True})),
        fake_ollama(lambda r: httpx.Response(200, json={"models": []})),
    )
    assert TestClient(app).get("/health").json() == {"ok": True, "keyward": True, "ollama": True, "model": "m"}


def test_health_reports_ollama_down_but_halo_still_ok():
    def down(req):
        raise httpx.ConnectError("refused")

    app = create_app(
        SETTINGS,
        fake_keyward(lambda r: httpx.Response(200, json={"ok": True})),
        fake_ollama(down),
    )
    body = TestClient(app).get("/health").json()
    assert body["ok"] is True and body["ollama"] is False and body["keyward"] is True
