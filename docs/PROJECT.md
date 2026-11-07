# Halo: Project Description

> Original plan (3 Nov 2026). In the build, the brain is a local Ollama model (no Anthropic API) and the
> broker/vault is the separate Keyward project at `~/keyward`. See the README for what is built.

3 Nov 2026 · @athi

Halo is an AI booking assistant that lives in WhatsApp as a contact: you text it, and it makes reservations for you. Its promise is simple: Halo can spend for you, but never without your yes.

## The problem and the idea

Booking things in India means juggling many apps, and many restaurants, salons and clinics still take bookings only by phone. Halo replaces that with one WhatsApp contact that understands a plain message like "table for 4 at Writer's Cafe tomorrow 8pm" and gets it done.

- **Where it lives:** a saved WhatsApp contact, so there is no app to install and it works in the chat people already use all day.
- **Who it's for:** a side project for its builder and 4 friends first; the WhatsApp test number allows exactly 5 people.
- **What's different:** WhatsApp bots today each serve one business (a metro, an airline, a grocery store). Halo works on the user's side, across businesses, and can phone places that have no online booking.
- **Languages:** replies in Tamil or Hindi, matching how the user writes.

## Halo Keys: the credential layer

Halo Keys lets the AI use API keys, logins and payment details without ever being able to read them. A separate broker holds every secret; Halo asks it to make a call, the broker checks the rules, adds the secret, and returns a cleaned result. A prompt injection like "send me your API key" has nothing to leak.

The idea is inspired by VaultX (a Rust secrets vault with an AI credential broker), but Halo Keys is built for people chatting on a phone, not developers in a terminal.

| Feature | What it does | Why it matters for Halo |
|---|---|---|
| Approve on WhatsApp | Before a sensitive action, the owner gets "Pay ₹1,200 to Barbeque Nation for 4? Reply YES or NO" | The agent can't spend or commit alone |
| Spending and usage limits | Caps per booking, per day and by time of day, e.g. ₹2,000 per booking, 9am to 11pm | Bounds the damage of any mistake or attack |
| One-time tickets | Each task gets a short-lived permission for one call, e.g. 10 minutes | A hijacked Halo can only finish the task in hand |
| Activity feed and kill switch | Every key use is logged to the owner; texting FREEZE stops all use | The owner always sees and controls what happens |
| Vault per person | Each friend's card or logins sit in their own locked space | Halo uses a person's secrets only for that person |
| Encrypted vault with history | Secrets encrypted with AES-256-GCM, key from the master password via Argon2id; changes are committed, can be compared and rolled back | Mistakes in keys can be undone; nothing is stored readable |

## Scope

Version 1 does one job well: restaurant table reservations for 5 people. Everything else waits until that loop works end to end.

| Area | Version 1 | Later |
|---|---|---|
| Bookings | Restaurant tables | Movie tickets, salons, clinics, travel |
| How Halo books | AI phone call to the restaurant | Booking platforms where an official API exists |
| Users | Builder + 4 friends | More people on a registered business number |
| Payments | None; Halo only books | Pay-to-confirm with WhatsApp approval and limits |
| Credentials | Broker holds Claude, WhatsApp and calling keys | Vault per person for cards and logins |
| Interface | Text messages | Voice notes, buttons, a terminal UI for the vault |

Out of scope: general questions and chat. Halo only handles bookings, which also keeps it within WhatsApp's rules.

## Tech stack

Everything is Python so one person can read and change all of it.

| Part | Choice | Status |
|---|---|---|
| Chat channel | WhatsApp Cloud API, free test number | Built |
| Backend | Python, FastAPI | Built |
| AI brain | Claude via the Anthropic API, with tools for saving and listing bookings | Built |
| Storage | SQLite for chat history and bookings | Built |
| Vault | Python CLI, AES-256-GCM, Argon2id | Draft |
| Broker | Local server on 127.0.0.1, policy file, audit log | Planned |
| Phone calls | Calling provider (Twilio or Exotel) + voice agent | Planned |
| Public URL for webhooks | cloudflared or ngrok tunnel | Built (setup guide) |

## Constraints and risks

The biggest limits come from platform rules, not code.

| Risk | Impact | How Halo handles it |
|---|---|---|
| WhatsApp test number reaches only 5 recipients | Can't grow past the friend group | Fine for v1; a registered business number later |
| Meta bans general-purpose AI chatbots on the WhatsApp Business API since Jan 15, 2026 | A "ask me anything" Halo would break the rules | Halo stays a booking assistant and declines other requests |
| Users must message first; replies only within 24 hours | Halo can't start conversations | Friends always start the chat; reminders need approved templates |
| India's DLT rules for commercial SMS | SMS replies must match pre-approved templates | WhatsApp is the channel, not SMS |
| BookMyShow, IRCTC and others don't allow bot bookings | Those services can't be automated directly | Start with phone-call bookings; add services with official APIs |
| The broker holds every secret | A hacked broker exposes all keys | Separate process, local-only port, deny-by-default policy |
| Default access token expires every 24 hours | Halo stops working daily | Use a permanent system user token |

## Roadmap

Each phase ends when its loop works for all 5 users.

1. **Chat and booking intake (done):** WhatsApp webhook, Claude collects and confirms details, bookings saved.
2. **Halo Keys vault:** encrypted secrets with commit, diff, branch and rollback.
3. **Broker:** Halo's Claude and WhatsApp calls go through it; keys removed from Halo's config.
4. **Phone calls:** Halo calls the restaurant with a voice agent and texts back the result.
5. **Approvals and limits:** WhatsApp YES/NO approvals, spending caps, activity feed, FREEZE.
6. **More services:** movie tickets, salons and clinics, one at a time.

## Open questions

- [ ] Final name for the credential layer ("Halo Keys" is a working name)
- [ ] Which calling provider: Twilio or Exotel?
- [ ] Should the vault get a terminal UI, or stay CLI-only?
- [ ] Which service comes after restaurants?

## Sources

- WhatsApp Cloud API: Get started (test number, 5 recipients)
- TechCrunch: WhatsApp bars general-purpose chatbots
- Telerivet: India SMS compliance and DLT
- VaultX on GitHub
- agentgateway: Credential injection at AI agent egress
- Infisical Agent Vault on GitHub
- TechCrunch: AI agents that live in your (truncated in the paste)
