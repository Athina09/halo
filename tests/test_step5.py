from datetime import date

import pytest

from evals.cases import CASES, NOW
from evals.grade import CLAIM, grade
from evals.run import comparison, report, run_model
from halo.ollama import OllamaError


def reply(text="", **call):
    calls = [{"function": {"name": n, "arguments": a}} for n, a in call.items()]
    return {"content": text, "tool_calls": calls}


def oracle(case):
    """What a perfect model would answer for this case."""
    want = case["expect"]
    return reply("Which restaurant?") if want["tool"] is None else reply(**{want["tool"]: want.get("args", {})})


class FakeLlm:
    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def chat(self, messages, tools=None):
        self.seen.append(messages)
        if len(self.seen) == 1:  # warm-up
            return reply("hello")
        text = messages[-1]["content"]
        return self.answer(next(c for c in CASES if c["text"] == text and (len(messages) > 3) == bool(c["history"])))


def test_there_are_30_well_formed_cases():
    assert len(CASES) == 30 and len({c["id"] for c in CASES}) == 30
    assert {"English", "Tamil", "Hindi", "Mixed", "Typos"} <= {c["group"] for c in CASES}
    for c in CASES:
        assert c["text"].strip()
        t = c["expect"]["tool"]
        assert t in (None, "save_booking_request", "listings", "cancel_booking")
        if t == "save_booking_request":
            assert set(c["expect"]["args"]) == {"restaurant", "date", "time", "party_size", "name"}


def test_expected_dates_agree_with_the_fixed_now():
    assert (NOW.weekday(), NOW.date()) == (5, date(2026, 11, 7))  # Saturday
    assert date(2026, 11, 8).weekday() == 6 and date(2026, 11, 9).weekday() == 0 and date(2026, 11, 13).weekday() == 4
    for c in CASES:
        d = c["expect"].get("args", {}).get("date")
        if d:
            assert date.fromisoformat(d) >= NOW.date()  # never expect a past date


def test_oracle_scores_everything():
    s = run_model("fake", "", 1, llm=FakeLlm(oracle))
    assert (s["score"], s["total"]) == (30, 30) and all(r["ok"] for r in s["results"])
    assert "30/30 (100%)" in report(s) and "FAIL" not in report(s)


def test_a_model_that_always_chats_fails_exactly_the_tool_cases():
    s = run_model("chatty", "", 1, llm=FakeLlm(lambda c: reply("Sure, tell me more!")))
    assert s["score"] == sum(c["expect"]["tool"] is None for c in CASES)
    assert "FAIL en-1" in report(s)


def test_ollama_errors_count_as_failures_with_their_kind():
    class Slow(FakeLlm):
        def chat(self, messages, tools=None):
            if self.seen:
                raise OllamaError("timed out after 1s", "slow")
            self.seen.append(messages)
            return reply("hello")

    s = run_model("slow", "", 1, llm=Slow(None))
    assert s["score"] == 0 and s["results"][0]["why"].startswith("slow:")


def case_of(id):
    return next(c for c in CASES if c["id"] == id)


@pytest.mark.parametrize("answer, ok", [
    (dict(save_booking_request=dict(restaurant="saravana bhavan", date="2026-11-08", time="20:00", party_size="4", name="priya")), True),
    (dict(save_booking_request=dict(restaurant="Sarvana Bhavan", date="2026-11-08", time="20:00", party_size=4, name="Priya")), True),
    (dict(save_booking_request=dict(restaurant="Saravana Bhavan", date="2026-11-08", time="8pm", party_size=4, name="Priya")), False),
    (dict(save_booking_request=dict(restaurant="Saravana Bhavan", date="2026-11-09", time="20:00", party_size=4, name="Priya")), False),
    (dict(save_booking_request=dict(restaurant="Murugan Idli Shop", date="2026-11-08", time="20:00", party_size=4, name="Priya")), False),
    (dict(save_booking_request=dict(restaurant="Saravana Bhavan", date="2026-11-08", time="20:00", party_size=5, name="Priya")), False),
    (dict(save_booking_request=dict(restaurant="Saravana Bhavan", date="2026-11-08", time="20:00", party_size=True, name="Priya")), False),
    (dict(listings={}), False),
    (dict(delete_all={}), False),
])
def test_grading_of_a_save_request(answer, ok):
    assert grade(case_of("en-1"), reply(**answer))[0] is ok


def test_grading_other_expectations():
    assert grade(case_of("ask-1"), reply("Which restaurant?"))[0]
    assert not grade(case_of("ask-1"), reply(""))[0]                        # empty reply
    assert not grade(case_of("ask-1"), reply(listings={}))[0]               # acted instead of asking
    assert grade(case_of("ta-4"), reply(listings={}))[0]
    assert grade(case_of("typo-3"), reply(cancel_booking={"booking_id": "7"}))[0]
    assert not grade(case_of("typo-3"), reply(cancel_booking={"booking_id": 8}))[0]
    two = {"content": "", "tool_calls": reply(listings={})["tool_calls"] * 2}
    assert not grade(case_of("ta-4"), two)[0]                                # exactly one call expected


def test_booked_claim_heuristic():
    assert CLAIM.search("Your table is booked!") and CLAIM.search("Confirmed for 8pm")
    assert not CLAIM.search("It is not booked yet") and not CLAIM.search("Which restaurant?")
    s = run_model("liar", "", 1, llm=FakeLlm(lambda c: reply("Great, your table is booked!")))
    assert s["claims_booked"] == 30 and "WARNING" in report(s)


def test_comparison_sorts_best_first():
    a = {"model": "a", "score": 10, "total": 30, "avg_s": 1.0, "max_s": 2.0}
    b = {"model": "b", "score": 25, "total": 30, "avg_s": 5.0, "max_s": 9.0}
    lines = comparison([a, b]).splitlines()
    assert lines[3].split()[0] == "b" and lines[4].split()[0] == "a"
