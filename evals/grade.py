import difflib
import re

from halo.agent import _parse_call

# Heuristic for rule 4 (Halo never says a table is booked). Reported as a warning, not scored.
CLAIM = re.compile(r"(?<!not )(?<!n't )\b(booked|confirmed)\b", re.I)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _int(v):
    try:
        return None if isinstance(v, bool) else int(str(v).strip())
    except ValueError:
        return None


def _arg_ok(key: str, want, got) -> bool:
    if got is None:
        return False
    if key in ("party_size", "booking_id"):
        return _int(got) == want
    if key == "restaurant":  # typos and spelling differences are fine
        return difflib.SequenceMatcher(None, _norm(want), _norm(got)).ratio() >= 0.8
    if key == "name":
        return str(got).strip().lower() == want.lower()
    return str(got).strip() == want  # date, time: exact YYYY-MM-DD / HH:MM


def grade(case: dict, msg: dict) -> tuple[bool, str]:
    """(passed, why not). Looks only at the model's first reply, so no tool is ever run."""
    calls, want = msg["tool_calls"], case["expect"]
    if want["tool"] is None:
        if calls:
            name, args = _parse_call(calls[0])
            return False, f"called {name or 'an unknown tool'} {args} instead of replying"
        return (True, "") if msg["content"].strip() else (False, "empty reply")
    if len(calls) != 1:
        return False, f"expected one {want['tool']} call, got {len(calls)} calls"
    name, args = _parse_call(calls[0])
    if name != want["tool"]:
        return False, f"called {name or 'an unknown tool'}, expected {want['tool']}"
    bad = [f"{k}: want {v!r}, got {args.get(k)!r}" for k, v in want.get("args", {}).items()
           if not _arg_ok(k, v, args.get(k))]
    return (False, "; ".join(bad)) if bad else (True, "")
