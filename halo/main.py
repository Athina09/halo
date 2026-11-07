import logging

from fastapi import FastAPI

from .agent import Agent
from .config import Settings
from .db import Store
from .fallback import Fallback
from .calls import Calls
from .handler import make_handler, make_notifier
from .keyward import Keyward
from .ollama import Ollama
from .restaurants import PHONES
from .voice import build_voice_router
from .webhook import Handler, build_router

log = logging.getLogger("halo")


def create_app(
    settings: Settings | None = None,
    keyward: Keyward | None = None,
    ollama: Ollama | None = None,
    store: Store | None = None,
    handler: Handler | None = None,
) -> FastAPI:
    s = settings or Settings.from_env()
    kw = keyward or Keyward(s.keyward_url, s.keyward_agent_token)
    llm = ollama or Ollama(s.ollama_url, s.ollama_model, s.ollama_timeout)

    db = store or Store(s.db_path)

    calls = Calls(db, kw, make_notifier(s.whatsapp_phone_number_id, kw), public_url=s.public_url,
                  account_sid=s.twilio_account_sid, from_number=s.twilio_from, phones=PHONES)
    handler = handler or make_handler(s.whatsapp_phone_number_id, kw, Agent(llm, db), Fallback(db), db,
                                      owner=s.owner_number, start_call=calls.start)

    app = FastAPI(title="Halo")
    app.include_router(build_router(s, kw, db, handler))
    app.include_router(build_voice_router(calls))

    @app.get("/health")
    def health():
        return {"ok": True, "keyward": kw.healthy(), "ollama": llm.reachable(), "model": s.ollama_model}

    return app


app = create_app()
