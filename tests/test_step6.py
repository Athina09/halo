"""Phase 4: phone calls to restaurants. Fake Keyward (httpx.MockTransport) and fake WhatsApp notifier."""
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from halo.calls import Calls, classify
from halo.db import Store
from halo.handler import make_handler
from halo.keyward import Keyward
from halo.voice import build_voice_router

OWNER, FRIEND = "919000000001", "919000000002"
NUMBER = "+914400000000"


class World:
    def __init__(self, tmp_path, phones=None, twilio_fails=False):
        self.store = Store(str(tmp_path / "h.db"))
        self.twilio_fails, self.requests, self.passes_dropped, self.told = twilio_fails, [], 0, []
        kw = Keyward("http://kw", "tok", client=httpx.Client(transport=httpx.MockTransport(self._kw)))
        self.calls = Calls(self.store, kw, lambda phone, key, text: self.told.append((phone, text)),
                           public_url="https://halo.example", account_sid="ACtest", from_number="+914499999999",
                           phones={"Saravana Bhavan": NUMBER} if phones is None else phones)
        app = FastAPI()
        app.include_router(build_voice_router(self.calls))
        self.http = TestClient(app)
        self.booking = self.store.add_booking(FRIEND, "Saravana Bhavan", "2026-11-08", "19:30", 4, "Priya")

    def _kw(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/passes" and req.method == "POST":
            return httpx.Response(200, json={"pass": "p1"})
        if req.url.path == "/passes":
            self.passes_dropped += 1
            return httpx.Response(200, json={})
        if req.url.path.startswith("/use/twilio"):
            self.requests.append((req.url.path, req.headers, parse_qs(req.content.decode())))
            return httpx.Response(502) if self.twilio_fails else httpx.Response(201, json={"sid": "CA123"})
        return httpx.Response(404)

    def token(self) -> str:
        _, _, form = self.requests[-1]
        return form["Url"][0].rsplit("/", 1)[1]


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.mark.parametrize("speech,outcome", [
    ("Yes, we have a table", "accepted"), ("haan available hai", "accepted"), ("okay", "accepted"),
    ("No, we are full", "declined"), ("sorry not available", "declined"), ("nahi", "declined"),
    ("", "unclear"), ("what time was that", "unclear"),
])
def test_classify(speech, outcome):
    assert classify(speech) == outcome


def test_start_asks_twilio_through_keyward_with_no_credentials(w):
    assert "Calling Saravana Bhavan" in w.calls.start(w.booking)
    path, headers, form = w.requests[0]
    assert path == "/use/twilio/2010-04-01/Accounts/ACtest/Calls.json"
    assert headers["x-keyward-pass"] == "p1" and "authorization" not in headers
    assert form["To"] == [NUMBER] and form["Url"][0].startswith("https://halo.example/voice/")
    assert w.passes_dropped == 1


def test_one_call_at_a_time_per_request(w):
    w.calls.start(w.booking)
    assert "already in progress" in w.calls.start(w.booking)
    assert len(w.requests) == 1


@pytest.mark.parametrize("phones,booking,msg", [
    ({}, 1, "no phone number"), ({"Saravana Bhavan": "44-000"}, 1, "no phone number"), (None, 99, "No open request"),
])
def test_start_refuses_bad_input_without_calling(tmp_path, phones, booking, msg):
    w = World(tmp_path, phones)
    assert msg in w.calls.start(booking)
    assert w.requests == []


def test_start_refuses_when_not_configured(w):
    w.calls._url = "http://insecure"
    assert "not set up" in w.calls.start(w.booking)


def test_twilio_failure_is_reported_and_allows_retry(tmp_path):
    w = World(tmp_path, twilio_fails=True)
    assert "could not start" in w.calls.start(w.booking)
    assert not w.store.active_call(w.booking)


def test_intro_speaks_the_request_and_escapes_names(w):
    w.store._run("UPDATE bookings SET name = ? WHERE id = ?", ("A&B <x>", w.booking))
    w.calls.start(w.booking)
    r = w.http.post(f"/voice/{w.token()}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "table for 4 people on 8 November at 7:30 PM" in r.text
    assert "A&amp;B &lt;x&gt;" in r.text


def test_yes_confirms_and_tells_the_person_once(w):
    w.calls.start(w.booking)
    t = w.token()
    r = w.http.post(f"/voice/{t}/answer", data={"SpeechResult": "Yes we do"})
    assert "<Hangup/>" in r.text
    assert w.store.get_booking(w.booking)["status"] == "confirmed"
    assert len(w.told) == 1 and w.told[0][0] == FRIEND and "said yes" in w.told[0][1]
    w.http.post(f"/voice/{t}/status", data={"CallStatus": "completed"})  # Twilio's final callback
    assert len(w.told) == 1


def test_no_keeps_it_a_request(w):
    w.calls.start(w.booking)
    w.http.post(f"/voice/{w.token()}/answer", data={"SpeechResult": "sorry we are full"})
    assert w.store.get_booking(w.booking)["status"] == "requested"
    assert "said no table" in w.told[0][1]


@pytest.mark.parametrize("provider,words", [("no-answer", "Nobody answered"), ("busy", "Nobody answered"),
                                            ("completed", "did not give a clear answer")])
def test_unanswered_calls_confirm_nothing(w, provider, words):
    w.calls.start(w.booking)
    w.http.post(f"/voice/{w.token()}/status", data={"CallStatus": provider})
    assert words in w.told[0][1]
    assert w.store.get_booking(w.booking)["status"] == "requested"


def test_unknown_or_finished_tokens_get_404_and_change_nothing(w):
    assert w.http.post("/voice/nope").status_code == 404
    assert w.http.post("/voice/nope/answer", data={"SpeechResult": "yes"}).status_code == 404
    w.calls.start(w.booking)
    t = w.token()
    w.http.post(f"/voice/{t}/answer", data={"SpeechResult": "no"})
    assert w.http.post(f"/voice/{t}").status_code == 404
    assert w.http.post(f"/voice/{t}/answer", data={"SpeechResult": "yes"}).status_code == 404
    assert w.store.get_booking(w.booking)["status"] == "requested"


def test_confirmed_requests_show_in_listings_and_cancel_list_stays_open_only(w):
    from halo.tools import listings
    w.store.confirm_booking(w.booking)
    out = listings(w.store, FRIEND, {}, None)
    assert out["requests"] == [] and out["confirmed_by_phone_call"][0]["id"] == w.booking
    assert w.store.cancel_booking(FRIEND, w.booking) is False


# --- the owner's CALL command ---

class Boom:
    def reply(self, *a):
        raise AssertionError("the model must never see a CALL command")


def test_only_the_owner_can_start_a_call(tmp_path):
    started, sent = [], []

    def kw_handler(r: httpx.Request):
        if r.url.path == "/passes" and r.method == "POST":
            return httpx.Response(200, json={"pass": "p"})
        if "/use/whatsapp" in r.url.path:
            sent.append(r.content.decode())
        return httpx.Response(200, json={})

    kw = Keyward("http://kw", "tok", client=httpx.Client(transport=httpx.MockTransport(kw_handler)))
    store = Store(str(tmp_path / "c.db"))
    h = make_handler("PNID", kw, Boom(), None, store, owner=OWNER,
                     start_call=lambda n: started.append(n) or f"Calling #{n}")
    h({"id": "m1", "from": OWNER, "type": "text", "text": "call 7", "reply_id": ""})
    assert started == [7] and "Calling #7" in sent[0]
    with pytest.raises(AssertionError):  # a friend's "call 7" is no command: it reaches the model (Boom)
        h({"id": "m2", "from": FRIEND, "type": "text", "text": "call 7", "reply_id": ""})
    assert started == [7]
