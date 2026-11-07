# CLAUDE.md

Halo is a WhatsApp booking assistant (restaurant table requests only, v1). The brain is an
open-source model running locally with Ollama (http://localhost:11434). The agent loop and tools
are our own Python code. All WhatsApp calls go through Keyward (`~/keyward`, http://127.0.0.1:8787).
There is NO "ai" route in Keyward: the model is local.

## Rules

1. No cloud AI and no AI API keys, ever. Only the local Ollama model.
2. No secrets in Halo's code, `.env`, logs or DB. WhatsApp goes through Keyward with a fresh task
   pass per message.
3. The model never acts directly. It can only REQUEST a tool; our code checks the arguments
   (dates in future, party size 1-20, required fields present) before running it.
4. Halo never says a table is booked. It saves a request.
5. Fallback: if Ollama is down, slow (>20 s) or returns something invalid twice, switch that person
   to the button-based booking flow (reply buttons + list messages).
6. Tests first, with a fake Ollama and fake Keyward. Run `pytest -q` after every step.

## Tech

Python 3.11+ (venv is on 3.13), FastAPI, httpx, SQLite, pytest. Talk to Ollama's HTTP API directly
with httpx (no AI SDKs). Model name comes from env `OLLAMA_MODEL`.

## Commands

```bash
.venv/bin/pytest -q                              # tests
.venv/bin/uvicorn halo.main:app --port 8000      # run Halo
```

## Layout

- `halo/config.py`: settings from env
- `halo/keyward.py`: Keyward client (passes, verify, inbound, send)
- `halo/ollama.py`: Ollama client (chat with tools, timeout, reachability)
- `halo/main.py`: FastAPI app, `/health`
- `halo/agent.py`, `tools.py`, `handler.py`, `fallback.py`: agent loop, validated tools, sending, button flow
- `halo/calls.py`, `voice.py`: owner-only `CALL <id>` starts a Twilio call through Keyward; webhooks record the answer
- `evals/`: 30 sample messages + scorer for comparing local models (`python -m evals.run --model NAME`)
- `tests/`: pytest, fakes via `httpx.MockTransport`

## Working style

Build one step at a time, explain simply, and wait for "next" after each step.
