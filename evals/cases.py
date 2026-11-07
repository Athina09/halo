"""30 sample messages with the tool call we expect. Later these double as fine-tuning examples.

"Now" is fixed at Saturday 2026-11-07 20:00 IST, so tomorrow = 2026-11-08, Monday = 2026-11-09,
Friday = 2026-11-13. expect.tool is a tool name, or None when the model should just reply (ask for
what is missing, or say it can't help). Only the args listed are checked.
"""
from datetime import datetime

from halo.tools import IST

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=IST)

SAVE = "save_booking_request"
ASK = {"tool": None}


def save(restaurant, date, time, party_size, name):
    return {"tool": SAVE, "args": {"restaurant": restaurant, "date": date, "time": time,
                                   "party_size": party_size, "name": name}}


def case(id, group, text, expect, history=()):
    return {"id": id, "group": group, "text": text, "expect": expect, "history": list(history)}


CASES = [
    # English: everything given
    case("en-1", "English", "Table for 4 at Saravana Bhavan tomorrow at 8pm, name Priya",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Priya")),
    case("en-2", "English", "Book 2 seats at Murugan Idli Shop on Monday 7:30 pm for Arun",
         save("Murugan Idli Shop", "2026-11-09", "19:30", 2, "Arun")),
    case("en-3", "English", "Need a table for 10 people at Dindigul Thalappakatti on 2026-11-14 at 21:00 under Kavitha",
         save("Dindigul Thalappakatti", "2026-11-14", "21:00", 10, "Kavitha")),
    case("en-4", "English", "I want a table tonight at 9pm at Saravana Bhavan for 3, name Ravi",
         save("Saravana Bhavan", "2026-11-07", "21:00", 3, "Ravi")),
    case("en-5", "English", "Reserve for 6 at Murugan Idli Shop day after tomorrow 1pm, name Meena",
         save("Murugan Idli Shop", "2026-11-09", "13:00", 6, "Meena")),
    case("en-6", "English", "Table for two at Saravana Bhavan this Friday 8:30pm, Sam",
         save("Saravana Bhavan", "2026-11-13", "20:30", 2, "Sam")),
    # Details missing: ask, never guess
    case("ask-1", "Missing details", "Hi, I want to book a table", ASK),
    case("ask-2", "Missing details", "Table for 4 tomorrow", ASK),
    case("ask-3", "Missing details", "Saravana Bhavan tomorrow 8pm", ASK),
    case("ask-4", "Missing details", "Book Murugan Idli Shop for 5 people", ASK),
    # Tamil
    case("ta-1", "Tamil", "நாளை இரவு 8 மணிக்கு Saravana Bhavan-ல 4 பேருக்கு டேபிள் வேணும், பேரு Priya",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Priya")),
    case("ta-2", "Tamil", "திங்கள் மதியம் 1 மணிக்கு Murugan Idli Shop-ல 2 பேருக்கு டேபிள் புக் பண்ணுங்க, பேரு Karthik",
         save("Murugan Idli Shop", "2026-11-09", "13:00", 2, "Karthik")),
    case("ta-3", "Tamil", "எனக்கு ஒரு டேபிள் வேணும்", ASK),
    case("ta-4", "Tamil", "என் பதிவுகளைக் காட்டுங்க", {"tool": "listings"}),
    case("ta-5", "Tamil", "booking 3 ஐ cancel பண்ணுங்க", {"tool": "cancel_booking", "args": {"booking_id": 3}}),
    # Hindi
    case("hi-1", "Hindi", "कल रात 8 बजे Saravana Bhavan में 4 लोगों के लिए टेबल चाहिए, नाम Rahul",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Rahul")),
    case("hi-2", "Hindi", "सोमवार दोपहर 1 बजे Dindigul Thalappakatti में 6 लोगों की टेबल बुक करो, नाम Sneha",
         save("Dindigul Thalappakatti", "2026-11-09", "13:00", 6, "Sneha")),
    case("hi-3", "Hindi", "मुझे टेबल चाहिए", ASK),
    case("hi-4", "Hindi", "मेरी बुकिंग दिखाओ", {"tool": "listings"}),
    case("hi-5", "Hindi", "बुकिंग 5 कैंसल कर दो", {"tool": "cancel_booking", "args": {"booking_id": 5}}),
    # Mixed: Tanglish, Hinglish, code-switching
    case("mix-1", "Mixed", "Anna naalaiku night 8 mani ku Saravana Bhavan la 4 per ku table venum, name Deepa",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Deepa")),
    case("mix-2", "Mixed", "Bhai kal 9 baje Murugan Idli Shop mein 3 log ka table, naam Vikram",
         save("Murugan Idli Shop", "2026-11-08", "21:00", 3, "Vikram")),
    case("mix-3", "Mixed", "table venum for 2 people tomorrow 7pm Saravana Bhavan, name Lakshmi",
         save("Saravana Bhavan", "2026-11-08", "19:00", 2, "Lakshmi")),
    case("mix-4", "Mixed", "yaar Monday 8:30 pm ko Dindigul Thalappakatti mein 5 log, naam Imran",
         save("Dindigul Thalappakatti", "2026-11-09", "20:30", 5, "Imran")),
    # Typos
    case("typo-1", "Typos", "tabel for 4 tomorow at sarvana bhavan 8pm, name Priya",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Priya")),
    case("typo-2", "Typos", "bok 2 seets at murugan idly shop mondy 7:30pm for arun",
         save("Murugan Idli Shop", "2026-11-09", "19:30", 2, "Arun")),
    case("typo-3", "Typos", "cancl booking 7", {"tool": "cancel_booking", "args": {"booking_id": 7}}),
    case("typo-4", "Typos", "wat r my bookngs", {"tool": "listings"}),
    # Off topic, and a follow-up that completes an earlier request
    case("other-1", "Other", "What's the weather today?", ASK),
    case("other-2", "Other", "Priya",
         save("Saravana Bhavan", "2026-11-08", "20:00", 4, "Priya"),
         history=[{"role": "user", "content": "Table for 4 at Saravana Bhavan tomorrow 8pm"},
                  {"role": "assistant", "content": "Sure! What name should I put it under?"}]),
]
