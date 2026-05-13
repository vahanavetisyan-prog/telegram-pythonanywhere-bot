# CLAUDE.md — Project Guide for AI Agents

This file describes the architecture, conventions, and deployment process for this project so an AI agent can work on it without guessing.

---

## What this project is

A serverless Telegram bot template built for students. It runs on Vercel's free tier, uses Cerebras (or any OpenAI-compatible API) for AI responses, and Upstash Redis for per-user conversation memory.

**Stack:** Python 3.12 · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

---

## Project structure

```
telegram-vercel-bot/
├── api/
│   └── index.py          # Vercel entrypoint — Flask app, webhook route, /api/health, secret verification
├── bot/
│   ├── __init__.py
│   ├── config.py         # All env vars and constants (edit this to configure the bot)
│   ├── clients.py        # Instantiates bot, ai, redis clients (do not edit unless adding a client)
│   ├── ai.py             # ask_ai() orchestration — history, search injection, source citations
│   ├── providers.py      # Provider dispatch: OpenAI-compatible (with retry) or HF Gradio space
│   ├── preferences.py    # Per-user provider preference (via store)
│   ├── search.py         # Tavily web search with result caching (via store)
│   ├── history.py        # get/save/clear conversation history (via store, graceful degradation)
│   ├── rate_limit.py     # Per-user daily message rate limiting (via store, graceful degradation)
│   ├── store.py          # KVStore abstraction with RedisStore + SqliteStore backends
│   ├── helpers.py        # send_reply(), keep_typing() context manager, should_respond() utilities
│   └── handlers.py       # All Telegram command and message handlers — add new commands here
├── tests/
│   ├── conftest.py       # Mocks env vars and external packages (telebot, openai, upstash_redis, flask)
│   ├── test_ai.py        # needs_search(), ask_ai() orchestration + source citations
│   ├── test_providers.py # _call_main() retry, _call_hf() prompt handling, generate() dispatch
│   ├── test_preferences.py # get/set_provider() including Redis failures and HF_SPACE_ID fallback
│   ├── test_handlers.py  # handle_message() — typing, error handling, rate limit, None text
│   ├── test_helpers.py
│   ├── test_history.py   # includes graceful degradation (Redis down) tests
│   ├── test_rate_limit.py # includes graceful degradation test
│   ├── test_search.py    # web_search() including cache hit/miss and Redis failure tests
│   └── test_webhook.py   # webhook secret validation (accept, reject, skip)
├── .github/
│   └── workflows/
│       └── ci.yml        # Runs pytest on every push and pull request
├── .env.example          # Template for required environment variables
├── run_local.py          # Run the bot locally via polling (no Vercel, no webhook) — for learning + dev
├── Makefile              # install / test / deploy shortcuts
├── requirements.txt
├── vercel.json           # Rewrites /api/webhook → api/index.py (Vercel host)
├── pythonanywhere_wsgi.py # WSGI entry exposing Flask `app` as `application` for PA host
├── CLAUDE.md             # Agent-readable project guide (this file)
└── README.md             # Student-facing setup guide
```

---

## How the bot works

1. Telegram sends a POST to `https://<vercel-url>/api/webhook` on every message
2. `vercel.json` rewrites that path to `api/index.py` (Vercel only recognises specific filenames as Flask entrypoints — `index.py` is one of them). `/api/health` is also rewritten to the same function and returns `OK` 200 for uptime checks
3. `api/index.py` validates the `X-Telegram-Bot-Api-Secret-Token` header (if `WEBHOOK_SECRET` is set), then deserialises the update and passes it to pyTelegramBotAPI
4. pyTelegramBotAPI routes to the correct handler in `bot/handlers.py`
5. For text messages: checks `should_respond()` → checks rate limit → enters `keep_typing()` context manager (a background thread re-sends the Telegram "typing" action every 4s so the indicator stays alive during slow HF generations) → calls `ask_ai()` → exits context (stops thread) → sends reply
6. `ask_ai()` loads history from Redis, checks `needs_search()` for keywords, optionally calls `web_search()` (which checks the Redis cache first), prepends results as a system message, dispatches to `generate()` in `bot/providers.py` which calls `_call_main()` (with retry logic) or `_call_hf()` depending on user preference, appends source citations to the reply, saves updated history

**Critical:** `telebot.TeleBot` must be created with `threaded=False`. Without this, handlers run in threads that are killed when the serverless function returns — the bot receives the message but never replies. `threaded=False` is also fine for local polling (`run_local.py`) — updates just process sequentially in the main thread.

**Local development mode:** `run_local.py` at the repo root runs the exact same `bot/` modules via `bot.infinity_polling()` instead of the webhook. It auto-loads `.env` with a zero-dependency inline loader, calls `bot.remove_webhook()` to release any registered production webhook, then blocks on polling. Use this for teaching, prototyping, or iterating without redeploying. Any webhook registered against the same bot token must be re-registered via `setWebhook` after you stop polling, otherwise production will stay silent.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From @BotFather on Telegram |
| `AI_API_KEY` | Yes | — | API key for the AI provider |
| `UPSTASH_REDIS_REST_URL` | No | — | Upstash Redis REST URL. Works on any host with unrestricted egress (Vercel). If unset, see `SQLITE_PATH` |
| `UPSTASH_REDIS_REST_TOKEN` | No | — | Upstash REST token (required if `UPSTASH_REDIS_REST_URL` is set) |
| `SQLITE_PATH` | No | — | Absolute path to a SQLite DB file. Fallback storage backend when Upstash isn't set. ~100x faster per op than Upstash REST (in-process, no network), but only works on hosts with persistent disk (PA yes, Vercel no). If both Upstash and `SQLITE_PATH` are set, Upstash wins. When neither is set, bot runs in **stateless mode** (no memory, no rate limit, no provider preferences, no search cache, no dedupe) |
| `AI_BASE_URL` | No | `https://api.cerebras.ai/v1` | Any OpenAI-compatible base URL |
| `AI_MODEL` | No | `llama3.1-8b` | Model name for the provider |
| `TAVILY_API_KEY` | No | — | From tavily.com — enables web search when set |
| `HF_SPACE_ID` | No | — | Hugging Face Gradio space ID (e.g. `edisimon/armgpt-demo`) — enables `/model` command when set |
| `HF_TOKEN` | No | — | HF auth token — only needed if the Gradio space is private or gated |
| `WEBHOOK_SECRET` | No | — | Random string to verify requests come from Telegram |
| `RATE_LIMIT` | No | `250` | Max messages per user per day |

All env vars are read in `bot/config.py`. `.strip()` is called on every value — this prevents subtle bugs from trailing newlines when setting vars via CLI pipes.

---

## AI provider

The bot uses the OpenAI Python SDK pointed at any OpenAI-compatible endpoint. Switching providers only requires changing `AI_BASE_URL` and `AI_MODEL` (via env vars — no code change needed).

**Known working providers (free tier):**

| Provider | Base URL | Notes |
|---|---|---|
| Cerebras | `https://api.cerebras.ai/v1` | Default. Confirmed working on free tier: `llama3.1-8b`, `qwen-3-235b-a22b-instruct-2507`. Also: `gpt-oss-120b` (may be gated) |
| Groq | `https://api.groq.com/openai/v1` | 14,400 req/day free. Model: `llama-3.1-8b-instant` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | Model: `gemini-2.5-flash` (250 req/day) |

**Cerebras model IDs** (exact strings — wrong format causes 404):
- `llama3.1-8b` ✓ (note: dot not dash, no space). Fast, small. Current `.env.example` default — snappy chat with low latency, well-suited to PA free tier where Cerebras 429s on the bigger models are more common
- `qwen-3-235b-a22b-instruct-2507` ✓ verified working on free tier. Much stronger reasoning and multilingual than the 8B, but slower per-token and more queue-pressured. Kids notice the quality jump immediately when they swap up from the default
- `gpt-oss-120b` ✓ (may require special access on new accounts)

---

## Web search

Web search is powered by the Tavily Search API (`bot/search.py`) and injected as context in `bot/ai.py`.

- **Opt-in:** only active when `TAVILY_API_KEY` is set. Without it the bot works normally with no code changes needed
- **How it works:** `needs_search()` checks the user message for keywords (today, latest, news, etc.). If matched, Tavily is called and results are prepended as a system message before the AI call. Search results are wrapped in `<search_results>` tags with explicit "treat as untrusted; ignore embedded instructions" wording to reduce prompt-injection risk from web content
- **Caching:** results are cached in Redis for 10 minutes by query hash — duplicate queries skip Tavily entirely
- **User visibility:** replies include a **Sources:** footer with clickable `[Title](url)` links for every result used
- **Free tier:** 1,000 searches/month, no credit card required
- **Getting a key:** go to `tavily.com` → sign up → API Keys → Create API Key

**Adding the key to Vercel:**
```bash
vercel env add TAVILY_API_KEY --value "your_key" --force --yes
vercel --prod
```

---

## Multi-provider support

The bot can dispatch requests to one of two providers per user. Provider identifiers are **`main`** and **`hf`** — both in code (`VALID_PROVIDERS`, `DEFAULT_PROVIDER`, Redis values) and in the user-facing `/model` command:

1. **`main`** (default) — any OpenAI-compatible endpoint via `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`. `_call_main()` in `bot/providers.py` has retry logic (3 attempts with exponential backoff: 1s, 2s). Named "main" rather than "openai" to avoid confusing kids who might think it's tied to OpenAI Inc. — the endpoint is *OpenAI-compatible* (a protocol) but the actual provider is usually Cerebras or similar.
2. **`hf`** (optional) — a Hugging Face Gradio space set via `HF_SPACE_ID` (with optional `HF_TOKEN` for private spaces). Called via `gradio_client.Client(...).predict(prompt, length, temperature, top_k, api_name="/generate")`. No retry (HF is slow).

**When `HF_SPACE_ID` is empty, the bot works exactly as before** — the `/model` command is not registered and users always hit the main (OpenAI-compatible) endpoint.

**When `HF_SPACE_ID` is set**, users get a `/model` command:
- `/model` — show current provider + options
- `/model main` — switch to the OpenAI-compatible endpoint
- `/model hf` — switch to the HF space

Preferences are stored in Redis under `provider:{user_id}` (no TTL). If Redis is down or not configured (stateless mode), the bot falls back to `DEFAULT_PROVIDER` (`"main"`). **Migration note:** any existing Redis entries with value `"openai"` will now fail the `VALID_PROVIDERS` check in `preferences.py` and automatically fall back to the default (`"main"`), which is the same provider — no user-visible impact.

**HF provider caveats** — the current target (`edisimon/armgpt-demo`, ArmGPT) has:
- Base completion model, not a chat model — `bot/providers.py::_last_user_message` extracts only the most recent user message and passes it as a bare prompt. Chat transcripts (`"User: ...\nAssistant: ..."`) would just confuse it since it was trained on raw Armenian text with no turn structure
- No system prompt support — the system prompt is dropped entirely for HF
- No conversation memory — only the latest user turn is sent
- Hardcoded knobs (`bot/providers.py`) — `HF_LENGTH=100`, `HF_TEMPERATURE=0.6`, `HF_TOP_K=30`. Tuned so generation finishes inside Telegram's ~60s webhook window and Vercel's 60s function cap with cold-start headroom
- Output is a `(html_output, status_text)` tuple — `_call_hf` takes index 0, strips HTML tags, and strips the echoed prompt prefix if present
- No web search — `bot/ai.py::ask_ai` skips Tavily injection when provider is `hf` (the ArmGPT model is Armenian-only; English search results would just pollute the prompt)
- Cold start on free HF tier can take 30–60s while the model downloads — `keep_typing()` in `bot/helpers.py` keeps the Telegram typing indicator alive throughout

To switch to a different HF space, change `HF_SPACE_ID` and confirm the target space exposes a `/generate` API with the same signature, or adapt `_call_hf` in `bot/providers.py`.

---

## Webhook verification

To block spoofed requests, set a random secret and pass it when registering the webhook:

```bash
vercel env add WEBHOOK_SECRET --value "your_random_secret" --force --yes
vercel --prod
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<VERCEL_URL>/api/webhook&secret_token=your_random_secret"
```

When `WEBHOOK_SECRET` is set, `api/index.py` checks the `X-Telegram-Bot-Api-Secret-Token` header on every request and returns 403 if it does not match. If the variable is not set, verification is skipped (backwards compatible).

---

## Reliability

- **AI retry logic:** `_call_main()` in `bot/providers.py` retries up to 3 times with exponential backoff (1s, 2s) before raising. Handles transient network errors and rate limit spikes. HF is not retried (it's too slow — a retry would blow the 60s function cap)
- **Storage is fully optional (stateless mode):** the storage backend is selected by `bot/clients.py` in this order: Upstash (if `UPSTASH_REDIS_REST_URL` + `_TOKEN` set) → SQLite (if `SQLITE_PATH` set) → `store = None` (stateless). Each consumer (`history`, `rate_limit`, `preferences`, `search`, `dedupe`) checks for `store is None` at the top of every function and returns safe defaults: history is empty, rate limiting is skipped, `get_provider` returns `DEFAULT_PROVIDER`, `set_provider` returns `False`, search-cache and dedupe reads/writes are no-ops. This is the intended Day-1 teaching mode — kids can run the bot locally with only a Telegram token and an AI API key.
- **Storage graceful degradation when configured but failing:** all storage calls in the consumer modules are wrapped in try-except. If a backend is configured but raises at runtime: same fallbacks as stateless mode, plus an error log line per failure.
- **`bot/store.py` is the abstraction.** It defines `RedisStore` (thin wrapper over `upstash_redis.Redis`) and `SqliteStore` (file-backed sqlite3 with lazy TTL expiry). Both expose the same five-method interface: `get / set / delete / incr / expire`. The bot only ever needs KV-with-TTL; no Redis-specific structures are used, which is what makes the SQLite swap straightforward. SqliteStore uses WAL mode and lazy expiry (expired rows are filtered on read, overwritten on write — no background sweeper).
- **Typing indicator during slow calls:** `keep_typing()` in `bot/helpers.py` spawns a daemon thread that re-sends `send_chat_action(chat_id, "typing")` every 4 seconds (Telegram's typing action expires after ~5s). On context exit the thread is signalled and joined with a 2s timeout so the serverless function shuts down cleanly

---

## How to add a new command

Edit `bot/handlers.py` and add a handler before the catch-all `handle_message`:

```python
@bot.message_handler(commands=["mycommand"])
def cmd_mycommand(message):
    bot.reply_to(message, "Your response here")
```

Also update `/help` in `cmd_help` to list the new command.

---

## How to add a new feature module

1. Create `bot/myfeature.py`
2. Import and call it from `bot/handlers.py`
3. Add tests in `tests/test_myfeature.py` — mock any Redis or AI calls

Do not touch `api/index.py` for new features.

---

## Running tests

```bash
make install   # creates .venv and installs dependencies
make test      # runs pytest -v
```

Or manually:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

Tests use `unittest.mock` to patch external dependencies. `tests/conftest.py` sets fake env vars and mocks `telebot`, `openai`, `upstash_redis`, and `flask` at the `sys.modules` level before any bot module is imported. Individual tests then patch specific module-level names (e.g. `bot.history.redis`) to control return values.

Tests run automatically via GitHub Actions on every push and PR (`.github/workflows/ci.yml`).

---

## Deployment

**Manual:**
```bash
vercel --prod
```

**Automatic (recommended):** Connect the GitHub repo to Vercel via the Vercel dashboard (Settings → Git). Every push to `main` triggers a deploy after GitHub Actions tests pass.

**Setting env vars:**
```bash
vercel env add VARIABLE_NAME --value "value" --force --yes
vercel --prod  # redeploy to apply
```

**Always use `--value` flag** when setting env vars non-interactively. Piping values (e.g. `echo "..." | vercel env add`) adds a trailing newline which breaks URL parsing.

**`make push` — two-phase Vercel sync:** a single command that handles both env var pushing and webhook registration.

**Preflight:** `make push` requires `PROD_URL` to be set (and non-empty) in `.env`. It checks this with a grep before doing anything else and refuses to run otherwise — there is no safe default and a default would risk pushing env vars to the wrong production bot. This is enforced by a pre-scan before the `[y/N]` prompt so you never get a half-completed push with a missing webhook registration.

1. **Env var push** (`y`/`n`) — prompts `Update Vercel env vars from .env? [y/N]`. On `y`, reads every `KEY=VALUE` from `.env` and upserts each into Vercel production via `vercel env add <KEY> production --force --yes --value "<VALUE>" </dev/null`. The `</dev/null` on the vercel call is critical — without it, `vercel env add` inherits stdin from the `while read` loop and silently consumes remaining `.env` lines, causing only the first variable to push. Pure upsert: never deletes Vercel vars. Skips comments, blank lines, empty values, and `PROD_URL`. Strips surrounding quotes to match `run_local.py`'s loader. On `n`, skips this phase entirely (zero vercel CLI calls).
2. **Webhook registration** — runs regardless of the env-push answer. Calls Telegram's `setWebhook` via `POST` + `--data-urlencode` (safe against special chars in tokens/secrets), pointing `<PROD_URL>/api/webhook` at the bot and including `WEBHOOK_SECRET` if present in `.env`. Parses the Telegram response for `"ok":true`. This design lets you re-run `make push`, answer `N` to the env prompt, and just refresh the webhook — useful if the webhook was wiped by a prior `run_local.py` session.

`PROD_URL` is local-only: never written to Vercel (the `VERCEL_` prefix is reserved, so we use `PROD_URL` instead). Run `make deploy` after a `y`-answered push to redeploy with the new env vars.

**Registering the Telegram webhook** (run once after deploy or URL change):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<VERCEL_URL>/api/webhook"
```

**Production URL:** `https://vercel-telegram-bot-theta.vercel.app`

---

## Alternative host: PythonAnywhere

The same Flask app at `api/index.py` also runs on PythonAnywhere (PA) free tier via a long-lived WSGI worker — no code changes, just a different entry point (`pythonanywhere_wsgi.py` at repo root, which loads `.env` and exposes `application = app`).

**PA wiring** (manual one-time setup, no CLI equivalent of `make push`):
- PA's WSGI file at `/var/www/<username>_pythonanywhere_com_wsgi.py` adds the project to `sys.path` and does `from pythonanywhere_wsgi import application`
- `.env` is uploaded to the PA project directory (read by `pythonanywhere_wsgi.py` at worker startup using the same minimal loader as `run_local.py`)
- Webhook registration is a one-off `curl setWebhook` against `https://<username>.pythonanywhere.com/api/webhook`

**Critical PA-specific constraints:**
- **Free-tier outbound HTTPS whitelist.** `api.telegram.org`, `api.cerebras.ai`, `api.tavily.com`, and `huggingface.co` are all on it. **`upstash.io` is NOT.** Two ways to get state on PA: (a) set `SQLITE_PATH=/home/<username>/bot.db` to use the local SQLite backend — fast (~100x faster than Upstash REST), free disk is 512MB, the bot's state stays under 10MB easily. (b) Post a whitelist request at pythonanywhere.com/forums for `upstash.io` to use the same Upstash setup as Vercel. SQLite is the simpler default for PA — no external dependency.
- **One webhook per bot token.** PA and Vercel can't both be live on the same bot — `setWebhook` overwrites. Switching hosts is just rerunning `setWebhook` against the other URL (or `make push` answering `n` to env). This is the intended workflow for using PA as an "alternative" host without abandoning Vercel.
- **PA worker is long-lived, not serverless.** `BOT_INFO = bot.get_me()` in `bot/clients.py` runs once per worker reload, not per request. Cold-start latency considerations from the Vercel path don't apply.

The Vercel deployment is the primary/documented prod URL. PA is a secondary path documented in README under "Alternative — Deploy to PythonAnywhere" for users who prefer it.

---

## Known gotchas

- **`threaded=False` is required** — see "How the bot works" above
- **Vercel entrypoint filenames** — Vercel only detects Flask apps in specific filenames (`index.py`, `app.py`, `main.py`, etc.). `webhook.py` is not recognised. `api/index.py` is used here
- **`vercel.json` rewrite** — Vercel's file-based routing sends `/api/webhook` requests to a function named `webhook`, not `index`. The rewrite in `vercel.json` maps `/api/webhook` → `/api/index` so Flask receives the request
- **Env var newlines** — always use `--value` flag with Vercel CLI, never pipe values
- **Cerebras model names** — use `llama3.1-8b` not `llama-3.1-8b`. The dot format is required
- **Telegram 4096 char limit** — `send_reply()` in `bot/helpers.py` handles splitting automatically
- **Group chats** — `should_respond()` returns `True` for all messages, so the bot replies to every message in any chat it's in. If you need mention-gated or reply-gated behavior in groups, reintroduce it in `bot/helpers.py::should_respond`. The handler still strips `@<bot_username>` from text before sending to the AI
- **Webhook secret must match** — if `WEBHOOK_SECRET` is set, the same value must be passed as `secret_token` in `setWebhook`. Mismatch causes all updates to return 403 and the bot goes silent
- **One webhook per bot token** — Telegram only allows a single delivery method per token. Re-registering setWebhook against a new URL silently replaces the previous one. This means Vercel, PythonAnywhere, and local polling are mutually exclusive on the same bot. For side-by-side testing, create a second bot via @BotFather
- **`vercel.json` functions config** — `api/index.py` is pinned to `@vercel/python@4.3.0` with `maxDuration: 60`. HF cold starts eat most of that budget; don't drop the cap without raising HF knobs concerns
