from datetime import datetime

import pytest

from halo.db import Store
from halo.fallback import Fallback
from halo.tools import IST

PHONE, OTHER = "919000000001", "919000000002"
REST = {"Saravana Bhavan": ["Anna Nagar", "T Nagar"], "Murugan Idli Shop": ["Besant Nagar"]}


class Clock:
    now = datetime(2026, 11, 7, 20, 0, tzinfo=IST)  # Saturday 8pm

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "h.db"))


@pytest.fixture
def fb(store, clock):
    f = Fallback(store, clock, REST)
    f.seen = []  # every payload sent, to check WhatsApp's limits
    return f


def tap(fb, rid="", text="", phone=PHONE, switched=False):
    out = fb.handle({"id": "w", "from": phone, "type": "interactive" if rid else "text",
                     "text": text, "reply_id": rid}, switched)
    fb.seen.extend(out)
    return out


def ids(payloads):
    i = payloads[-1]["interactive"]
    if i["type"] == "button":
        return [b["reply"]["id"] for b in i["action"]["buttons"]]
    return [r["id"] for r in i["action"]["sections"][0]["rows"]]


def to_summary(fb, restaurant="rest:0", area="area:0", day="day:2026-11-08", t="time:19:30", people="ppl:4"):
    tap(fb)                      # menu
    tap(fb, "menu:book")
    tap(fb, restaurant)
    if area:
        tap(fb, area)
    tap(fb, day)
    tap(fb, t)
    tap(fb, people)
    return tap(fb, text="Priya")


def test_happy_path_saves_a_request_not_a_booking(fb, store):
    summary = to_summary(fb)
    assert ids(summary) == ["confirm", "edit", "cancel"]
    body = summary[-1]["interactive"]["body"]["text"]
    assert "Saravana Bhavan (Anna Nagar)" in body and "Sun 8 Nov at 7:30 PM" in body and "4 people" in body
    done = tap(fb, "confirm")
    [b] = store.bookings(PHONE)
    assert (b["restaurant"], b["date"], b["time"], b["party_size"], b["name"], b["status"]) == \
        ("Saravana Bhavan (Anna Nagar)", "2026-11-08", "19:30", 4, "Priya", "requested")
    assert "not booked yet" in done[0]["text"]["body"] and "confirmed" not in done[0]["text"]["body"].replace("We will confirm", "")
    assert store.get_flow(PHONE) is None and store.get_mode(PHONE) == "ai"


def test_every_payload_respects_whatsapp_limits(fb):
    to_summary(fb, people="ppl:more")  # exercises the typed-number path too
    for p in fb.seen:
        if p["type"] == "text":
            assert 0 < len(p["text"]["body"]) <= 1024
            continue
        i = p["interactive"]
        assert len(i["body"]["text"]) <= 1024
        if i["type"] == "button":
            bs = i["action"]["buttons"]
            assert len(bs) <= 3 and all(len(b["reply"]["title"]) <= 20 and len(b["reply"]["id"]) <= 256 for b in bs)
        else:
            rows = i["action"]["sections"][0]["rows"]
            assert len(rows) <= 10 and len(i["action"]["button"]) <= 20
            assert all(len(r["title"]) <= 24 and len(r.get("description", "")) <= 72 for r in rows)


def test_first_screen_is_the_menu_with_busy_note_when_switched(fb):
    out = tap(fb, text="table for 4 tomorrow", switched=True)
    assert "busy" in out[0]["text"]["body"] and ids(out) == ["menu:book", "menu:list", "menu:cancel"]


def test_wrong_input_repeats_the_step_without_moving(fb, store):
    tap(fb); tap(fb, "menu:book")
    out = tap(fb, text="a table please")                      # typed text at a list step
    assert "pick one" in out[0]["text"]["body"] and ids(out) == ["rest:0", "rest:1"]
    out = tap(fb, "rest:7")                                    # id we never offered
    assert ids(out) == ["rest:0", "rest:1"] and store.get_flow(PHONE)[0] == "restaurant"


def test_forged_ids_for_other_steps_are_rejected(fb, store):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0"); tap(fb, "area:0")
    tap(fb, "day:2020-01-01")   # past day
    tap(fb, "day:2026-12-31")   # beyond 7 days
    assert store.get_flow(PHONE)[0] == "day"
    tap(fb, "confirm")          # a summary id at the day step
    assert store.get_flow(PHONE)[0] == "day" and store.bookings(PHONE) == []


def test_menu_keyword_resets_mid_flow(fb, store):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0")
    out = tap(fb, text="menu")
    assert ids(out) == ["menu:book", "menu:list", "menu:cancel"] and store.get_flow(PHONE) == ("menu", {})


def test_single_area_restaurant_skips_area_step(fb, store):
    tap(fb); tap(fb, "menu:book")
    out = tap(fb, "rest:1")
    assert store.get_flow(PHONE)[0] == "day" and ids(out)[0] == "day:2026-11-07"


def test_days_and_times_hide_the_past(fb, clock):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0")
    days = ids(tap(fb, "area:0"))
    assert len(days) == 7 and days[0] == "day:2026-11-07"
    assert ids(tap(fb, days[0])) == ["time:20:30", "time:21:00", "time:21:30", "time:22:00"]


def test_today_disappears_when_no_slots_left(fb, clock):
    clock.now = datetime(2026, 11, 7, 23, 0, tzinfo=IST)
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0")
    days = ids(tap(fb, "area:0"))
    assert days[0] == "day:2026-11-08" and len(days) == 6


def test_ten_or_more_people_asks_for_a_number(fb, store):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0"); tap(fb, "area:0"); tap(fb, "day:2026-11-08"); tap(fb, "time:19:00")
    assert "10 to 20" in tap(fb, "ppl:more")[0]["text"]["body"]
    for bad in ("5", "21", "abc", "0", "-3"):
        assert "10 to 20" in tap(fb, text=bad)[0]["text"]["body"]
    assert store.get_flow(PHONE)[0] == "people_text"
    tap(fb, text="15")
    assert store.get_flow(PHONE)[1]["party_size"] == 15 and store.get_flow(PHONE)[0] == "name"


def test_name_must_be_present_and_short(fb, store):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0"); tap(fb, "area:0"); tap(fb, "day:2026-11-08"); tap(fb, "time:19:00"); tap(fb, "ppl:2")
    tap(fb, text="x" * 81)
    tap(fb, "ppl:3")  # a tap is not a name
    assert store.get_flow(PHONE)[0] == "name"
    tap(fb, text="Ravi")
    assert store.get_flow(PHONE)[0] == "summary"


def test_edit_restarts_and_cancel_discards(fb, store):
    to_summary(fb)
    assert ids(tap(fb, "edit")) == ["rest:0", "rest:1"]
    to_summary(fb)
    out = tap(fb, "cancel")
    assert "Nothing was saved" in out[0]["text"]["body"] and store.bookings(PHONE) == []
    assert store.get_flow(PHONE) is None and store.get_mode(PHONE) == "ai"


def test_confirm_after_time_passed_goes_back_to_day_step(fb, store, clock):
    to_summary(fb, day="day:2026-11-07", t="time:21:00")
    clock.now = datetime(2026, 11, 7, 21, 30, tzinfo=IST)
    out = tap(fb, "confirm")
    assert "no longer available" in out[0]["text"]["body"] and store.bookings(PHONE) == []
    assert store.get_flow(PHONE)[0] == "day" and "day:2026-11-07" in ids(out)


def test_my_requests_and_cancel_only_show_and_touch_own(fb, store):
    mine = store.add_booking(PHONE, "Saravana Bhavan", "2026-11-09", "20:00", 2, "Me")
    theirs = store.add_booking(OTHER, "Murugan Idli Shop", "2026-11-09", "20:00", 2, "Them")
    tap(fb)
    listing = tap(fb, "menu:list")
    assert f"#{mine}" in listing[0]["text"]["body"] and f"#{theirs}" not in listing[0]["text"]["body"]
    options = ids(tap(fb, "menu:cancel"))
    assert options == [f"cancel:{mine}", "back"]
    tap(fb, f"cancel:{theirs}")                      # forged: not offered
    assert len(store.bookings(OTHER)) == 1
    out = tap(fb, f"cancel:{mine}")
    assert "Cancelled" in out[0]["text"]["body"] and store.bookings(PHONE) == []


def test_menu_with_no_requests_says_so(fb):
    tap(fb)
    out = tap(fb, "menu:list")
    assert "no open" in out[0]["text"]["body"] and ids(out)[0] == "menu:book"
    assert "no open" in tap(fb, "menu:cancel")[0]["text"]["body"]


def test_two_people_have_independent_flows(fb, store):
    tap(fb); tap(fb, "menu:book"); tap(fb, "rest:0")
    tap(fb, phone=OTHER)
    assert store.get_flow(PHONE)[0] == "area" and store.get_flow(OTHER) == ("menu", {})


def test_stale_state_recovers_to_menu(fb, store):
    store.set_flow(PHONE, "area", {"restaurant": "Gone Cafe"})
    out = tap(fb, "area:0")
    assert ids(out) == ["menu:book", "menu:list", "menu:cancel"]
