import json
import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_messages (id TEXT PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT NOT NULL, at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS modes (phone TEXT PRIMARY KEY, mode TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flows (phone TEXT PRIMARY KEY, step TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, restaurant TEXT NOT NULL,
    date TEXT NOT NULL, time TEXT NOT NULL, party_size INTEGER NOT NULL, name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested', at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL, token TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'calling', provider_sid TEXT NOT NULL DEFAULT '',
    at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


class Store:
    """SQLite store. One short-lived connection per call keeps it safe across threads."""

    def __init__(self, path: str):
        self._path = path
        with closing(self._conn()) as c, c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        return c

    def _run(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with closing(self._conn()) as c, c:
            cur = c.execute(sql, args)
            cur.fetchall() if cur.description else None
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(sql, args)]

    def first_time(self, message_id: str) -> bool:
        """True the first time this WhatsApp message id is seen, False for retries."""
        return self._run("INSERT OR IGNORE INTO seen_messages (id) VALUES (?)", (message_id,)).rowcount == 1

    # conversation history (final texts only, never tool traces)
    def add_message(self, phone: str, role: str, content: str) -> None:
        self._run("INSERT INTO messages (phone, role, content) VALUES (?, ?, ?)", (phone, role, content))

    def history(self, phone: str, limit: int = 20) -> list[dict]:
        rows = self._all("SELECT role, content FROM messages WHERE phone = ? ORDER BY id DESC LIMIT ?", (phone, limit))
        return rows[::-1]

    # per-person mode: "ai" (default) or "buttons"
    def get_mode(self, phone: str) -> str:
        rows = self._all("SELECT mode FROM modes WHERE phone = ?", (phone,))
        return rows[0]["mode"] if rows else "ai"

    def set_mode(self, phone: str, mode: str) -> None:
        self._run("INSERT INTO modes (phone, mode) VALUES (?, ?) ON CONFLICT(phone) DO UPDATE SET mode = excluded.mode",
                  (phone, mode))

    # button-flow progress: current step plus what has been picked so far
    def get_flow(self, phone: str) -> tuple[str, dict] | None:
        rows = self._all("SELECT step, data FROM flows WHERE phone = ?", (phone,))
        return (rows[0]["step"], json.loads(rows[0]["data"])) if rows else None

    def set_flow(self, phone: str, step: str, data: dict) -> None:
        self._run("INSERT INTO flows (phone, step, data) VALUES (?, ?, ?) "
                  "ON CONFLICT(phone) DO UPDATE SET step = excluded.step, data = excluded.data",
                  (phone, step, json.dumps(data)))

    def clear_flow(self, phone: str) -> None:
        self._run("DELETE FROM flows WHERE phone = ?", (phone,))

    # booking requests (never "confirmed": the restaurant/owner does that outside Halo)
    def add_booking(self, phone: str, restaurant: str, date: str, time: str, party_size: int, name: str) -> int:
        return self._run(
            "INSERT INTO bookings (phone, restaurant, date, time, party_size, name) VALUES (?, ?, ?, ?, ?, ?)",
            (phone, restaurant, date, time, party_size, name)).lastrowid

    def bookings(self, phone: str) -> list[dict]:
        return self._all("SELECT id, restaurant, date, time, party_size, name, status FROM bookings "
                         "WHERE phone = ? AND status = 'requested' ORDER BY date, time", (phone,))

    def cancel_booking(self, phone: str, booking_id: int) -> bool:
        """Cancels only the caller's own open request."""
        return self._run("UPDATE bookings SET status = 'cancelled' WHERE id = ? AND phone = ? AND status = 'requested'",
                         (booking_id, phone)).rowcount == 1

    def get_booking(self, booking_id: int) -> dict | None:
        rows = self._all("SELECT id, phone, restaurant, date, time, party_size, name, status FROM bookings "
                         "WHERE id = ?", (booking_id,))
        return rows[0] if rows else None

    def confirm_booking(self, booking_id: int) -> bool:
        """Marks a request confirmed. Only called when the restaurant said yes on a phone call."""
        return self._run("UPDATE bookings SET status = 'confirmed' WHERE id = ? AND status = 'requested'",
                         (booking_id,)).rowcount == 1

    def confirmed_bookings(self, phone: str) -> list[dict]:
        return self._all("SELECT id, restaurant, date, time, party_size, name, status FROM bookings "
                         "WHERE phone = ? AND status = 'confirmed' ORDER BY date, time", (phone,))

    # phone calls to restaurants (one row per attempt; the token in the voice URL is the only key)
    def add_call(self, booking_id: int, token: str) -> int:
        return self._run("INSERT INTO calls (booking_id, token) VALUES (?, ?)", (booking_id, token)).lastrowid

    def call_by_token(self, token: str) -> dict | None:
        rows = self._all("SELECT id, booking_id, status FROM calls WHERE token = ?", (token,))
        return rows[0] if rows else None

    def active_call(self, booking_id: int) -> bool:
        return bool(self._all("SELECT 1 FROM calls WHERE booking_id = ? AND status = 'calling'", (booking_id,)))

    def set_call_sid(self, call_id: int, sid: str) -> None:
        self._run("UPDATE calls SET provider_sid = ? WHERE id = ?", (sid, call_id))

    def finish_call(self, call_id: int, status: str) -> bool:
        """True only for the first outcome of a call, so the person is told once."""
        return self._run("UPDATE calls SET status = ? WHERE id = ? AND status = 'calling'",
                         (status, call_id)).rowcount == 1
