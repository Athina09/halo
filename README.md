# Halo

Halo is a WhatsApp assistant that takes **restaurant table requests**. You and up to 4 friends
chat with it like any contact.

- The **brain** is an open-source model running on your own laptop with Ollama. No OpenAI, Google
  or Anthropic, no AI keys, no cost.
- The **body** is this Python code. It decides what is allowed. The model can only *ask* to save,
  list or cancel a request. Halo checks everything (future date, 1 to 20 people, all details present)
  before doing it.
- **Keyward** keeps the WhatsApp keys. Halo never holds one.
- Halo never says a table is booked. It saves a **request**.
- If the model is down, slow (over 20 seconds) or confused twice, that person is switched to a
  simple **button flow** (lists and buttons), so booking still works.

```
Your WhatsApp ──► Meta ──► cloudflared ──► Halo ──► Ollama (model on your laptop)
      ▲                                      │
      └──────── reply ◄── Keyward ◄──────────┘   (Keyward holds the WhatsApp token)
```

## What you need

- A Mac or PC. **RAM:** 8 GB runs a 3B model slowly. 16 GB is comfortable. (A 3B model uses about 2 to 3 GB.)
- Python 3.11 or newer
- Ollama: https://ollama.com
- Keyward (the broker): `git clone https://github.com/Athina09/Keyward ~/keyward && pip install -e ~/keyward`
- cloudflared: `brew install cloudflared` (a free tunnel so Meta can reach your laptop)
- A free Meta developer account with a WhatsApp test number

## 1. Install Halo

```bash
cd Halo
python3.13 -m venv .venv          # any Python 3.11+
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q               # all tests use fakes, no network needed
```

## 2. Install Ollama and pull a model

```bash
brew install ollama               # or download the app from ollama.com
ollama serve                      # skip if the app is already running
ollama pull qwen2.5:3b            # small, supports tools
ollama pull llama3.2:3b           # a second one to compare
```

Pick any model Ollama marks as supporting **tools**. Bigger models understand Tamil and Hindi
better but are slower. Remember Halo falls back to buttons after 20 seconds.

**Choose a model with the eval** (30 sample messages in English, Tamil, Hindi, mixed and typos):

```bash
.venv/bin/python -m evals.run --model qwen2.5:3b --model llama3.2:3b
```

It prints a score, the slowest reply, and what each failure got wrong, then ranks the models.
Put the winner in `OLLAMA_MODEL`. It does not check the reply language, so read a few replies
with `-v`.

## 3. Set up Keyward (whatsapp route and verifier, no ai route)

```bash
cd ~/keyward
keyward init                                   # pick a master password
cp ~/path/to/Halo/examples/keyward-rules.toml rules.toml
# edit rules.toml: your Phone number ID (2 places) and your own number
keyward set WHATSAPP_TOKEN                     # you type the values, hidden
keyward set WHATSAPP_APP_SECRET
keyward rules                                  # checks the file and that the secrets exist
keyward serve                                  # leave running; http://127.0.0.1:8787
keyward token agent                            # in another terminal: prints Halo's token
```

Do not put `KEYWARD_PASSWORD` in Halo's environment. Never paste the WhatsApp token or app secret
into Halo, its `.env`, or a chat. They only go into `keyward set`.

## 4. Configure Halo

```bash
cp .env.example .env
```

Fill in (no secrets here):

| Variable | What it is |
|---|---|
| `KEYWARD_AGENT_TOKEN` | from `keyward token agent` |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta, WhatsApp, API Setup |
| `WHATSAPP_VERIFY_TOKEN` | any text you choose; you type the same in Meta |
| `OWNER_NUMBER` | your number, country code first, digits only |
| `ALLOWED_NUMBERS` | up to 4 friends, comma separated |
| `OLLAMA_MODEL` | the model you chose |

Edit `halo/restaurants.py` for your real restaurants and areas (at most 10 restaurants).

## 5. Run everything

Four terminals:

```bash
ollama serve                                                   # 1 (if not already running)
keyward serve                                                  # 2
.venv/bin/uvicorn halo.main:app --env-file .env --port 8000    # 3
cloudflared tunnel --url http://localhost:8000                 # 4
```

Check it is alive:

```bash
curl localhost:8787/health      # {"ok":true,"frozen":false}
curl localhost:8000/health      # {"ok":true,"keyward":true,"ollama":true,"model":"..."}
```

If `keyward` or `ollama` shows `false`, start it. Halo still answers with buttons when Ollama is down.

## 6. Connect WhatsApp (Meta)

1. developers.facebook.com, Create App, Business, add **WhatsApp**.
2. WhatsApp, API Setup: note the free test number's **Phone number ID**. Add your own number in
   the "To" list and verify it with the code.
3. Make a permanent token (Business settings, System users, permission `whatsapp_business_messaging`)
   and find the **App secret** (App settings, Basic). Put both into Keyward only (step 3).
4. WhatsApp, Configuration: **Callback URL** = the `https://....trycloudflare.com` address that
   cloudflared printed, plus `/webhook`. **Verify token** = your `WHATSAPP_VERIFY_TOKEN`. Click
   Verify. Then subscribe to the **messages** field.
5. Save the test number as "Halo" on your phone and say hi.

The free cloudflared address **changes every time you restart it**. Paste the new one into
Meta each time.

## 7. Phone calls (optional)

Halo can phone a restaurant and ask if a table is free. Only **you** (`OWNER_NUMBER`) can start a
call, by texting `CALL 12` (12 is the request id). The model can never start one.

1. Get a Twilio account and a number. Put the credentials into Keyward as one secret:
   `keyward set TWILIO_CREDENTIALS` and type `ACxxxx:your_auth_token`. Never into Halo.
2. Copy the `[routes.twilio]` block of `examples/keyward-rules.toml` into Keyward's `rules.toml`
   (use your own Account SID), then `keyward rules`.
3. In `.env` set `HALO_PUBLIC_URL` (the cloudflared address), `TWILIO_ACCOUNT_SID`, `TWILIO_FROM`.
4. In `halo/restaurants.py` add each restaurant's number to `PHONES` (`+91...`). Halo calls no other number.
5. Text `CALL 12`. Halo phones, asks "is a table available, yes or no?", and tells the person who
   made the request what the restaurant said.

Good to know:
- A spoken **yes** marks the request `confirmed`. Anything else (no, no answer, unclear) leaves it a request.
- Twilio's speech recognition is a cloud service, but Halo holds no AI key and the model stays local.
- Twilio calls Halo's `/voice/<token>` links. The long random token in each link is the only key
  (Halo does not hold Twilio's auth token to check signatures), and a link stops working once the
  call has an outcome.
- Keyward limits calls to 10 a day and records each one in its receipts.
- English only for now.

## How it behaves

- Only `OWNER_NUMBER` and `ALLOWED_NUMBERS` get answers. Others are ignored.
- Every webhook is checked by Keyward first. Fake ones get a 403.
- Your own YES/NO/FREEZE messages to Keyward are passed through untouched.
- Every message gets a fresh, short-lived Keyward pass that is thrown away after the reply.
- WhatsApp may deliver a message twice. Halo handles each message id once.
- A "table request" is saved as `requested`. Someone confirms it outside Halo.
- Reply language follows the user (English, Tamil, Hindi, mixed). The button flow is English only.

## If something is wrong

| Problem | Try |
|---|---|
| Meta says it cannot verify the URL | Is cloudflared running? Did the URL end in `/webhook`? Same verify token? |
| No reply at all | `keyward receipts --today`, and Halo's terminal. Is your number in `OWNER_NUMBER` or `ALLOWED_NUMBERS`? |
| Webhook returns 403 | `WHATSAPP_APP_SECRET` in Keyward is not the app secret of this Meta app |
| Webhook returns 503 | Keyward is not running, or the agent token is wrong |
| Always buttons | `curl localhost:8000/health`. Is the model pulled (`ollama list`)? Too slow? Try a smaller one |
| Keyward 401/403 on sending | Phone number ID in `rules.toml` must match `WHATSAPP_PHONE_NUMBER_ID` |
| Keyward 423 | It is frozen: `keyward unfreeze` |

## Files

```
halo/main.py       app and /health          halo/agent.py     the loop (up to 4 rounds)
halo/webhook.py    verify, allowlist, dedupe  halo/tools.py    validated tools
halo/handler.py    sends replies             halo/fallback.py  button flow
halo/keyward.py    Keyward client            halo/ollama.py    Ollama client
halo/calls.py      restaurant phone calls    halo/voice.py     Twilio call webhooks
evals/             model scorecard           examples/keyward-rules.toml
```

Rules for working on this code are in `CLAUDE.md`. Run `.venv/bin/pytest -q` after every change.
