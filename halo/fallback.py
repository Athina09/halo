"""Button-based booking flow (a state machine), used when the AI is down, slow or confused.

menu -> restaurant -> area -> day -> time -> people -> name -> summary [Confirm][Edit][Cancel]

Progress lives in SQLite. Every tapped id is checked against the options we offered at that step,
and the final request goes through the same validation as the AI's tool (rule 3).
"""
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from .db import Store
from .restaurants import RESTAURANTS
from .tools import IST, save_booking_request

SLOTS = ["12:30", "13:00", "13:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30", "22:00"]
BUTTON_STEPS = {"menu", "summary"}
SWITCHED = "Sorry, our assistant is busy right now, so let's do this with buttons."
Option = tuple[str, str, str]  # (id, title, description)


def text_payload(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


def buttons_payload(body: str, options: list[Option]) -> dict:
    buttons = [{"type": "reply", "reply": {"id": i, "title": t}} for i, t, _ in options]
    return {"type": "interactive", "interactive": {"type": "button", "body": {"text": body},
                                                   "action": {"buttons": buttons}}}


def list_payload(body: str, label: str, options: list[Option]) -> dict:
    rows = [{"id": i, "title": t, **({"description": d} if d else {})} for i, t, d in options]
    return {"type": "interactive", "interactive": {"type": "list", "body": {"text": body},
                                                   "action": {"button": label, "sections": [{"title": "Options", "rows": rows}]}}}


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _clock(hhmm: str) -> str:
    return time.fromisoformat(hhmm).strftime("%I:%M %p").lstrip("0")


class Fallback:
    def __init__(self, store: Store, now: Callable[[], datetime] | None = None,
                 restaurants: dict[str, list[str]] | None = None):
        self._store = store
        self._now = now or (lambda: datetime.now(IST))
        self._rest = restaurants if restaurants is not None else RESTAURANTS

    def handle(self, message: dict, switched: bool = False) -> list[dict]:
        """WhatsApp message payloads (without "to") to send back, in order."""
        phone, now = message["from"], self._now()
        text, rid = (message.get("text") or "").strip(), message.get("reply_id") or ""
        flow = self._store.get_flow(phone)
        if flow is None or (not rid and text.lower() == "menu"):
            return self._goto(phone, "menu", {}, now, SWITCHED if switched else None)
        step, data = flow
        try:
            if step in ("name", "people_text"):
                return getattr(self, f"_{step}")(phone, data, text, rid, now)
            options = self._options(step, data, now, phone)
            if rid not in {o[0] for o in options}:
                return self._again(phone, step, data, now, "Please pick one of the options.")
            return getattr(self, f"_{step}")(phone, data, rid, now)
        except (KeyError, ValueError, IndexError):  # stale state, e.g. restaurant list changed
            return self._goto(phone, "menu", {}, now)

    # ---- plumbing ----------------------------------------------------------

    def _goto(self, phone, step, data, now, note=None) -> list[dict]:
        self._store.set_flow(phone, step, data)
        out = [text_payload(note)] if note else []
        return out + self._prompt(phone, step, data, now)

    def _again(self, phone, step, data, now, note) -> list[dict]:
        return [text_payload(note)] + self._prompt(phone, step, data, now)

    def _finish(self, phone: str) -> None:
        self._store.clear_flow(phone)
        self._store.set_mode(phone, "ai")  # next message tries the assistant again

    def _prompt(self, phone, step, data, now) -> list[dict]:
        if step == "people_text":
            return [text_payload("How many people? Type a number from 10 to 20.")]
        if step == "name":
            return [text_payload("What name should the request be under?")]
        options = self._options(step, data, now, phone)
        body = self._body(step, data)
        if step in BUTTON_STEPS:
            return [buttons_payload(body, options)]
        return [list_payload(body, "Choose", options)]

    def _body(self, step: str, data: dict) -> str:
        if step == "summary":
            where = data["restaurant"] + (f" ({data['area']})" if data.get("area") else "")
            when = f"{_day(date.fromisoformat(data['date']))} at {_clock(data['time'])}"
            return f"Please check:\n{where}\n{when}\n{data['party_size']} people\nName: {data['name']}"
        return {"menu": "What would you like to do?", "restaurant": "Which restaurant?",
                "area": "Which area?", "day": "Which day?", "time": "What time?",
                "people": "How many people?", "cancel_pick": "Which request should I cancel?"}[step]

    def _slots(self, d: date, now: datetime) -> list[str]:
        return [s for s in SLOTS if datetime.combine(d, time.fromisoformat(s), IST) > now]

    def _options(self, step, data, now, phone) -> list[Option]:
        if step == "menu":
            return [("menu:book", "Book a table", ""), ("menu:list", "My requests", ""),
                    ("menu:cancel", "Cancel a request", "")]
        if step == "restaurant":
            return [(f"rest:{i}", name[:24], "") for i, name in enumerate(self._rest)]
        if step == "area":
            return [(f"area:{i}", a[:24], "") for i, a in enumerate(self._rest[data["restaurant"]])]
        if step == "day":
            days = [(now + timedelta(days=k)).date() for k in range(7)]
            return [(f"day:{d.isoformat()}", _day(d) if d != now.date() else f"Today ({_day(d)})", "")
                    for d in days if self._slots(d, now)]
        if step == "time":
            return [(f"time:{s}", _clock(s), "") for s in self._slots(date.fromisoformat(data["date"]), now)]
        if step == "people":
            return [(f"ppl:{n}", f"{n} person" if n == 1 else f"{n} people", "") for n in range(1, 10)] + \
                   [("ppl:more", "10 or more", "")]
        if step == "summary":
            return [("confirm", "Confirm", ""), ("edit", "Edit", ""), ("cancel", "Cancel", "")]
        if step == "cancel_pick":
            return [(f"cancel:{b['id']}", f"#{b['id']} {b['restaurant']}"[:24], f"{b['date']} {b['time']}")
                    for b in self._store.bookings(phone)[:9]] + [("back", "Back", "")]
        raise KeyError(step)

    # ---- steps: each takes the tapped id (or typed text) and returns the next prompt ----

    def _menu(self, phone, data, rid, now):
        if rid == "menu:book":
            return self._goto(phone, "restaurant", {}, now)
        open_requests = self._store.bookings(phone)
        if rid == "menu:list":
            if not open_requests:
                return self._goto(phone, "menu", {}, now, "You have no open table requests.")
            lines = [f"#{b['id']} {b['restaurant']}, {_day(date.fromisoformat(b['date']))} "
                     f"{_clock(b['time'])}, {b['party_size']} people" for b in open_requests]
            return self._goto(phone, "menu", {}, now, "Your open requests:\n" + "\n".join(lines))
        if not open_requests:  # menu:cancel
            return self._goto(phone, "menu", {}, now, "You have no open table requests.")
        return self._goto(phone, "cancel_pick", {}, now)

    def _restaurant(self, phone, data, rid, now):
        name = list(self._rest)[int(rid.split(":")[1])]
        data = {"restaurant": name}
        areas = self._rest[name]
        if len(areas) == 1:  # nothing to choose
            data["area"] = areas[0]
            return self._goto(phone, "day", data, now)
        return self._goto(phone, "area", data, now)

    def _area(self, phone, data, rid, now):
        data["area"] = self._rest[data["restaurant"]][int(rid.split(":")[1])]
        return self._goto(phone, "day", data, now)

    def _day(self, phone, data, rid, now):
        data["date"] = rid.split(":", 1)[1]
        return self._goto(phone, "time", data, now)

    def _time(self, phone, data, rid, now):
        data["time"] = rid.split(":", 1)[1]
        return self._goto(phone, "people", data, now)

    def _people(self, phone, data, rid, now):
        if rid == "ppl:more":
            return self._goto(phone, "people_text", data, now)
        data["party_size"] = int(rid.split(":")[1])
        return self._goto(phone, "name", data, now)

    def _people_text(self, phone, data, text, rid, now):
        if rid or not text.isdigit() or not 10 <= int(text) <= 20:
            return self._again(phone, "people_text", data, now, "Please type a number from 10 to 20.")
        data["party_size"] = int(text)
        return self._goto(phone, "name", data, now)

    def _name(self, phone, data, text, rid, now):
        if rid or not text or len(text) > 80:
            return self._again(phone, "name", data, now, "Please type a name (up to 80 letters).")
        data["name"] = text
        return self._goto(phone, "summary", data, now)

    def _summary(self, phone, data, rid, now):
        if rid == "edit":
            return self._goto(phone, "restaurant", {}, now)
        if rid == "cancel":
            self._finish(phone)
            return [text_payload("Okay, cancelled. Nothing was saved.")]
        where = data["restaurant"] + (f" ({data['area']})" if data.get("area") else "")
        result = save_booking_request(self._store, phone, {
            "restaurant": where, "date": data["date"], "time": data["time"],
            "party_size": data["party_size"], "name": data["name"]}, now)
        if "error" in result:  # e.g. the chosen time passed while they were deciding
            return self._goto(phone, "day", data, now, "Sorry, that time is no longer available. Please pick again.")
        self._finish(phone)
        return [text_payload(
            f"Request #{result['booking_id']} saved: {where}, {_day(date.fromisoformat(data['date']))} "
            f"at {_clock(data['time'])}, {data['party_size']} people, under {data['name']}.\n"
            "We will confirm it separately. It is not booked yet.")]

    def _cancel_pick(self, phone, data, rid, now):
        if rid == "back":
            return self._goto(phone, "menu", {}, now)
        done = self._store.cancel_booking(phone, int(rid.split(":")[1]))
        note = "Cancelled." if done else "I could not find that request."
        return self._goto(phone, "menu", {}, now, note)
