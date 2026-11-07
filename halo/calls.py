"""Phone calls to restaurants. Twilio's credentials live in Keyward; Halo only asks for a pass."""
import logging
import re
import secrets
from collections.abc import Callable
from datetime import datetime
from xml.sax.saxutils import escape

from .db import Store
from .keyward import Keyward, KeywardError

log = logging.getLogger("halo.calls")

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
NO = re.compile(r"\b(no|nahi|nahin|illai|illa|sorry|full|booked|unavailable|not available|cannot|can't|cant)\b")
YES = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|confirm|confirmed|fine|available|haan|han|aam|sari)\b")

Notify = Callable[[str, str, str], None]  # (person's number, key for the Keyward pass, text)


def classify(speech: str) -> str:
    """accepted / declined / unclear. "No" wins, so "not available" is never read as yes."""
    s = speech.lower()
    if NO.search(s):
        return "declined"
    return "accepted" if YES.search(s) else "unclear"


def spoken_when(b: dict) -> str:
    d = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
    return f"{d.day} {d:%B} at {d:%I:%M %p}".replace(" 0", " ")


def twiml(*parts: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{"".join(parts)}</Response>'


class Calls:
    def __init__(self, store: Store, keyward: Keyward, notify: Notify, *, public_url: str,
                 account_sid: str, from_number: str, phones: dict[str, str]):
        self._store, self._kw, self._notify = store, keyward, notify
        self._url, self._sid, self._from, self._phones = public_url, account_sid, from_number, phones

    def start(self, booking_id: int) -> str:
        """Called only for the owner's CALL command. Returns the text to send back to the owner."""
        if not (self._url.startswith("https://") and self._sid and E164.match(self._from)):
            return "Phone calls are not set up yet (HALO_PUBLIC_URL, TWILIO_ACCOUNT_SID, TWILIO_FROM)."
        b = self._store.get_booking(booking_id)
        if not b or b["status"] != "requested":
            return f"No open request with id {booking_id}."
        number = self._phones.get(b["restaurant"], "")
        if not E164.match(number):
            return f"I have no phone number for {b['restaurant']}."
        if self._store.active_call(booking_id):
            return f"A call for request {booking_id} is already in progress."

        token = secrets.token_urlsafe(24)
        call_id = self._store.add_call(booking_id, token)
        p = self._kw.new_pass(f"call-{call_id}", ["twilio"], uses=1, ttl=120)
        try:
            out = self._kw.use_form(p, "twilio", f"/2010-04-01/Accounts/{self._sid}/Calls.json", {
                "To": number, "From": self._from, "Timeout": "30",
                "Url": f"{self._url}/voice/{token}",
                "StatusCallback": f"{self._url}/voice/{token}/status",
                "StatusCallbackEvent": ["completed"],
            })
        except KeywardError as e:
            log.warning("call %s could not start: %s", call_id, e)
            self._store.finish_call(call_id, "failed")
            return "I could not start the call (Keyward refused or Twilio is down). Check `keyward receipts --today`."
        finally:
            self._kw.drop_pass(p)
        self._store.set_call_sid(call_id, str(out.get("sid", "")))
        return f"Calling {b['restaurant']} now about request {booking_id}. I will message you what they say."

    # --- Twilio webhooks (the token in the URL is the only key) ---

    def intro(self, token: str) -> str | None:
        call = self._store.call_by_token(token)
        if not call or call["status"] != "calling":
            return None
        b = self._store.get_booking(call["booking_id"])
        if not b:
            return None
        ask = (f"Hello. This is Halo, an assistant calling for {escape(b['name'])}. "
               f"They would like a table for {b['party_size']} people on {spoken_when(b)}. "
               f"Is a table available? Please say yes or no.")
        return twiml(
            f'<Gather input="speech" language="en-IN" speechTimeout="auto" timeout="6" '
            f'action="/voice/{token}/answer" method="POST" hints="yes,no"><Say language="en-IN">{ask}</Say></Gather>',
            '<Say language="en-IN">Sorry, I did not hear an answer. Goodbye.</Say>')

    def answer(self, token: str, speech: str) -> str | None:
        call = self._store.call_by_token(token)
        if not call or call["status"] != "calling":
            return None
        outcome = classify(speech)
        self._finish(call, outcome)
        bye = {"accepted": "Thank you. Goodbye.", "declined": "Understood, thank you. Goodbye.",
               "unclear": "Sorry, I did not understand. Goodbye."}[outcome]
        return twiml(f'<Say language="en-IN">{bye}</Say><Hangup/>')

    def status(self, token: str, provider_status: str) -> None:
        """The call ended without a spoken answer (nobody picked up, busy, hung up)."""
        call = self._store.call_by_token(token)
        if call:
            self._finish(call, "no_answer" if provider_status in ("no-answer", "busy", "canceled") else
                         "failed" if provider_status == "failed" else "unclear")

    def _finish(self, call: dict, outcome: str) -> None:
        if not self._store.finish_call(call["id"], outcome):
            return  # already handled: tell the person only once
        b = self._store.get_booking(call["booking_id"])
        if not b:
            return
        what = f"{b['restaurant']}, {b['party_size']} people, {b['date']} {b['time']} for {b['name']}"
        if outcome == "accepted":
            self._store.confirm_booking(b["id"])
            text = f"{b['restaurant']} said yes on the phone: {what}. Request {b['id']} is confirmed."
        elif outcome == "declined":
            text = f"{b['restaurant']} said no table for request {b['id']} ({what}). It is still saved as a request."
        elif outcome == "no_answer":
            text = f"Nobody answered at {b['restaurant']} for request {b['id']}. It is still saved as a request."
        else:
            text = (f"The call to {b['restaurant']} for request {b['id']} did not give a clear answer, "
                    f"so nothing is confirmed. Please check with them.")
        try:
            self._notify(b["phone"], f"call-{call['id']}", text)
        except KeywardError as e:
            log.warning("could not tell %s about call %s: %s", b["phone"], call["id"], e)
