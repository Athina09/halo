from datetime import datetime

import httpx
import pytest

from halo.agent import SYSTEM, Agent
from halo.db import Store
from halo.fallback import Fallback
from halo.handler import make_handler
from halo.keyward import Keyward
from halo.ollama import OllamaError
from halo.tools import IST

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=IST)  # a Saturday evening in India
PHONE, OTHER = "919000000001", "919000000002"


class FakeOllama:
    """Plays back scripted replies (a message dict or an OllamaError) and records what it was sent."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"content": "", "tool_calls": [], **item}


def say(text):
    return {"content": text}


def call(tool, /, **args):
    return {"tool_calls": [{"function": {"name": tool, "arguments": args}}]}


GOOD = dict(restaurant="Saravana Bhavan", date="2026-11-08", time="19:30", party_size=4, name="Priya")


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "h.db"))


def agent(store, *script):
    llm = FakeOllama(*script)
    return Agent(llm, store, now=lambda: NOW), llm


def test_plain_reply_is_returned_and_remembered(store):
    a, _ = agent(store, say("Which restaurant?"))
    assert a.reply(PHONE, "table for 4") == "Which restaurant?"
    assert store.history(PHONE) == [{"role": "user", "content": "table for 4"},
                                    {"role": "assistant", "content": "Which restaurant?"}]


def test_save_request_runs_tool_then_final_reply(store):
    a, llm = agent(store, call("save_booking_request", **GOOD), say("Request saved, we will confirm."))
    assert a.reply(PHONE, "...") == "Request saved, we will confirm."
    [b] = store.bookings(PHONE)
    assert (b["restaurant"], b["date"], b["time"], b["party_size"], b["status"]) == \
        ("Saravana Bhavan", "2026-11-08", "19:30", 4, "requested")
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and "Do not say the table is booked" in tool_msg["content"]


def test_tool_arguments_as_json_string_work(store):
    import json
    c = {"tool_calls": [{"function": {"name": "save_booking_request", "arguments": json.dumps(GOOD)}}]}
    a, _ = agent(store, c, say("ok"))
    a.reply(PHONE, "x")
    assert len(store.bookings(PHONE)) == 1


@pytest.mark.parametrize("change", [
    {"date": "2026-11-07", "time": "19:00"},   # earlier today
    {"date": "2025-01-01"},                    # past
    {"date": "tomorrow"},                      # not a date
    {"time": "7pm"},                           # not HH:MM
    {"party_size": 0}, {"party_size": 21}, {"party_size": "many"}, {"party_size": True},
    {"name": ""}, {"restaurant": "x" * 81},
])
def test_invalid_arguments_are_rejected_and_nothing_saved(store, change):
    a, llm = agent(store, call("save_booking_request", **{**GOOD, **change}), say("Could you check that?"))
    assert a.reply(PHONE, "x") == "Could you check that?"
    assert store.bookings(PHONE) == []
    assert "error" in llm.calls[1][-1]["content"]


def test_missing_fields_are_reported_to_the_model(store):
    a, llm = agent(store, call("save_booking_request", restaurant="X"), say("What time?"))
    a.reply(PHONE, "x")
    assert "missing" in llm.calls[1][-1]["content"] and store.bookings(PHONE) == []


def test_party_size_boundaries_accepted(store):
    for n in (1, 20):
        a, _ = agent(store, call("save_booking_request", **{**GOOD, "party_size": n}), say("ok"))
        a.reply(PHONE, "x")
    assert [b["party_size"] for b in store.bookings(PHONE)] == [1, 20]


def test_listings_and_cancel_only_touch_own_requests(store):
    mine = store.add_booking(PHONE, "A", "2026-11-09", "20:00", 2, "Me")
    theirs = store.add_booking(OTHER, "B", "2026-11-09", "20:00", 2, "Them")
    a, llm = agent(store, call("listings"), say("ok"))
    a.reply(PHONE, "my bookings")
    assert '"id": %d' % mine in llm.calls[1][-1]["content"] and '"id": %d' % theirs not in llm.calls[1][-1]["content"]

    a, llm = agent(store, call("cancel_booking", booking_id=theirs), say("not found"))
    a.reply(PHONE, "cancel")
    assert "error" in llm.calls[1][-1]["content"] and len(store.bookings(OTHER)) == 1

    a, _ = agent(store, call("cancel_booking", booking_id=mine), say("cancelled"))
    a.reply(PHONE, "cancel")
    assert store.bookings(PHONE) == []


def test_unknown_tool_is_not_run_and_counts_as_invalid(store):
    a, llm = agent(store, call("delete_everything"), say("Sorry, which restaurant?"))
    assert a.reply(PHONE, "x") == "Sorry, which restaurant?"
    assert "invalid tool call" in llm.calls[1][-1]["content"]


def test_two_invalid_replies_fall_back(store):
    a, _ = agent(store, say(""), say("  "))
    assert a.reply(PHONE, "x") is None
    a, _ = agent(store, OllamaError("bad json"), OllamaError("bad json"))
    assert a.reply(PHONE, "x") is None


def test_one_invalid_reply_then_good_is_fine(store):
    a, _ = agent(store, say(""), say("Hello!"))
    assert a.reply(PHONE, "hi") == "Hello!"


@pytest.mark.parametrize("kind", ["down", "slow"])
def test_down_or_slow_falls_back_immediately(store, kind):
    a, llm = agent(store, OllamaError("x", kind), say("never reached"))
    assert a.reply(PHONE, "hi") is None and len(llm.calls) == 1


def test_gives_up_after_four_rounds(store):
    a, llm = agent(store, *[call("listings")] * 6)
    assert a.reply(PHONE, "x") is None and len(llm.calls) == 4


def test_prompt_has_ist_date_and_history_capped_at_20(store):
    for i in range(30):
        store.add_message(PHONE, "user" if i % 2 == 0 else "assistant", f"m{i}")
    a, llm = agent(store, say("ok"))
    a.reply(PHONE, "latest")
    sent = llm.calls[0]
    assert "Saturday 2026-11-07 20:00" in sent[0]["content"] and "Asia/Kolkata" in SYSTEM
    assert len(sent) == 1 + 20 + 1 and sent[1]["content"] == "m10" and sent[-1]["content"] == "latest"


def test_history_is_per_person(store):
    store.add_message(OTHER, "user", "secret")
    a, llm = agent(store, say("ok"))
    a.reply(PHONE, "hi")
    assert all("secret" not in m["content"] for m in llm.calls[0])


# ---- handler: passes, sending, fallback switch ---------------------------

class Wire:
    def __init__(self):
        self.sent, self.passes, self.dropped = [], 0, 0
        self.kw = Keyward("http://kw", "tok", client=httpx.Client(transport=httpx.MockTransport(self._h)))

    def _h(self, req):
        if req.method == "POST" and req.url.path == "/passes":
            self.passes += 1
            return httpx.Response(200, json={"pass": f"p{self.passes}"})
        if req.method == "DELETE":
            self.dropped += 1
            return httpx.Response(200, json={})
        self.sent.append((req.headers["x-keyward-pass"], req.url.path, httpx.Response(200, content=req.content).json()))
        return httpx.Response(200, json={})


def msg(text="hi", mid="w1", typ="text"):
    return {"id": mid, "from": PHONE, "type": typ, "text": text, "reply_id": ""}


def test_handler_sends_reply_with_fresh_pass_per_message_and_drops_it(store):
    w = Wire()
    a, _ = agent(store, say("one"), say("two"))
    h = make_handler("123", w.kw, a, Fallback(store), store)
    h(msg(mid="w1")); h(msg(mid="w2"))
    assert [s[0] for s in w.sent] == ["p1", "p2"] and w.dropped == 2
    assert w.sent[0][1] == "/use/whatsapp/v21.0/123/messages"
    assert w.sent[0][2]["to"] == PHONE and w.sent[0][2]["text"]["body"] == "one"


def test_handler_switches_to_buttons_when_ollama_fails_and_stays_there(store):
    w = Wire()
    a, llm = agent(store, OllamaError("x", "down"))
    h = make_handler("123", w.kw, a, Fallback(store), store)
    h(msg(mid="w1")); h(msg(mid="w2"))
    assert store.get_mode(PHONE) == "buttons" and len(llm.calls) == 1  # 2nd message never hit the model
    assert 'buttons' in w.sent[0][2]['text']['body'] and w.sent[1][2]['type'] == 'interactive'


def test_handler_non_text_message_gets_polite_reply_without_model(store):
    w = Wire()
    a, llm = agent(store)
    make_handler("123", w.kw, a, Fallback(store), store)(msg(text="", typ="image"))
    assert llm.calls == [] and "text" in w.sent[0][2]["text"]["body"]
