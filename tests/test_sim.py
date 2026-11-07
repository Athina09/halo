from datetime import datetime, timedelta

import pytest

from halo.ollama import OllamaError
from halo.tools import IST
from sim.chat import Sim, render


class FakeOllama:
    def __init__(self, *script):
        self.script = list(script)

    def chat(self, messages, tools=None):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"content": "", "tool_calls": [], **item}

    def reachable(self):
        return True


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "sim.db")


def texts(out):
    return [render(p)[0] for p in out]


def test_ai_path_saves_a_request_and_replies(db):
    tomorrow = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")
    args = dict(restaurant="Saravana Bhavan", date=tomorrow, time="20:00", party_size=4, name="Priya")
    llm = FakeOllama({"tool_calls": [{"function": {"name": "save_booking_request", "arguments": args}}]},
                     {"content": "Request saved. We will confirm separately."})
    sim = Sim(llm, db)
    assert texts(sim.say("table for 4 tomorrow 8pm Saravana Bhavan, Priya")) == ["Request saved. We will confirm separately."]
    assert len(sim.store.bookings(sim.phone)) == 1


def test_button_flow_end_to_end_when_ollama_is_down(db):
    sim = Sim(FakeOllama(OllamaError("down", "down")), db)
    out = sim.say("table please")
    assert "busy" in texts(out)[0] and ("menu:book", "Book a table") in render(out[-1])[1]

    out = sim.tap("menu:book")
    for _ in range(4):                       # restaurant, area, day, time: take the first option
        out = sim.tap(render(out[-1])[1][0][0])
    out = sim.tap("ppl:2")
    out = sim.say("Priya")
    assert [i for i, _ in render(out[-1])[1]] == ["confirm", "edit", "cancel"]
    done = sim.tap("confirm")
    assert "not booked yet" in texts(done)[0]
    assert len(sim.store.bookings(sim.phone)) == 1 and sim.store.get_mode(sim.phone) == "ai"


def test_render_buttons_and_lists():
    assert render({"type": "text", "text": {"body": "hi"}}) == ("hi", [])
    buttons = {"type": "interactive", "interactive": {"type": "button", "body": {"text": "b"},
               "action": {"buttons": [{"type": "reply", "reply": {"id": "x", "title": "X"}}]}}}
    assert render(buttons) == ("b", [("x", "X")])
    lst = {"type": "interactive", "interactive": {"type": "list", "body": {"text": "l"},
           "action": {"button": "Choose", "sections": [{"rows": [{"id": "r", "title": "R", "description": "d"}]}]}}}
    assert render(lst) == ("l", [("r", "R (d)")])
