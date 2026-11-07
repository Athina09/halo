"""Tools the model may REQUEST. Our code validates every argument before anything runs."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Store

IST = ZoneInfo("Asia/Kolkata")

TOOLS = [
    {"type": "function", "function": {
        "name": "save_booking_request",
        "description": "Save a restaurant table REQUEST once you have every detail. Only call it when the "
                      "user has given restaurant, date, time, number of people and a name.",
        "parameters": {"type": "object", "properties": {
            "restaurant": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD, Asia/Kolkata"},
            "time": {"type": "string", "description": "HH:MM, 24-hour, Asia/Kolkata"},
            "party_size": {"type": "integer", "description": "1 to 20"},
            "name": {"type": "string", "description": "Name for the booking"}},
            "required": ["restaurant", "date", "time", "party_size", "name"]}}},
    {"type": "function", "function": {
        "name": "listings", "description": "List this user's open table requests.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "cancel_booking", "description": "Cancel one of this user's open table requests by its id.",
        "parameters": {"type": "object", "properties": {"booking_id": {"type": "integer"}},
                       "required": ["booking_id"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
REQUIRED = ("restaurant", "date", "time", "party_size", "name")


def _int(v) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def save_booking_request(store: Store, phone: str, args: dict, now: datetime) -> dict:
    missing = [k for k in REQUIRED if args.get(k) in (None, "")]
    if missing:
        return {"error": f"missing: {', '.join(missing)}. Ask the user for these."}
    restaurant, name = str(args["restaurant"]).strip(), str(args["name"]).strip()
    if not restaurant or not name or len(restaurant) > 80 or len(name) > 80:
        return {"error": "restaurant and name must be 1-80 characters."}
    party = _int(args["party_size"])
    if party is None or not 1 <= party <= 20:
        return {"error": "party_size must be a whole number from 1 to 20."}
    try:
        when = datetime.strptime(f"{str(args['date']).strip()} {str(args['time']).strip()}", "%Y-%m-%d %H:%M")
    except ValueError:
        return {"error": "date must be YYYY-MM-DD and time HH:MM (24-hour)."}
    if when.replace(tzinfo=IST) <= now:
        return {"error": "that date and time is in the past. Ask the user for a future one."}
    booking_id = store.add_booking(phone, restaurant, when.strftime("%Y-%m-%d"), when.strftime("%H:%M"), party, name)
    return {"ok": True, "booking_id": booking_id, "status": "requested",
            "note": "This is only a REQUEST. Do not say the table is booked or confirmed."}


def listings(store: Store, phone: str, args: dict, now: datetime) -> dict:
    return {"requests": store.bookings(phone), "confirmed_by_phone_call": store.confirmed_bookings(phone)}


def cancel_booking(store: Store, phone: str, args: dict, now: datetime) -> dict:
    booking_id = _int(args.get("booking_id"))
    if booking_id is None:
        return {"error": "booking_id must be a whole number."}
    if not store.cancel_booking(phone, booking_id):
        return {"error": "no open request with that id for this user."}
    return {"ok": True, "booking_id": booking_id, "status": "cancelled"}


_RUN = {"save_booking_request": save_booking_request, "listings": listings, "cancel_booking": cancel_booking}


def run_tool(store: Store, phone: str, name: str, args: dict, now: datetime) -> dict:
    return _RUN[name](store, phone, args, now)
