# Vercel Telegram Bot — Starter Template

A minimal Python Telegram bot running on Vercel (free tier) with persistent conversation memory via Upstash Redis and AI powered by Cerebras (llama3.1-8b).

**Stack:** Python · Flask · pyTelegramBotAPI · OpenAI SDK · Upstash Redis · Vercel

**All services used are free. No credit card required.**

> **Live demo:** <a href="https://t.me/vercel_telegram_ed_bot" target="_blank"><img src="https://img.shields.io/badge/Chat%20on-Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Chat on Telegram"/></a>

---

## What you will need to create

| Service | Purpose | Free tier |
|---|---|---|
| [Telegram](https://telegram.org) | The bot platform | Always free |
| [Cerebras](https://cloud.cerebras.ai) | AI API (llama3.1-8b) | 1M tokens/day, 30 req/min |
| [Upstash](https://upstash.com) | Redis for conversation memory | 10,000 req/day |
| [Vercel](https://vercel.com) | Hosting the bot | 100GB bandwidth/month |
| [GitHub](https://github.com) | Source code (Vercel deploys from here) | Always free |
| [Tavily](https://tavily.com) | Web search *(optional)* | 1,000 searches/month |

---

## Step 1 — Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `My AI Bot`) and a username ending in `bot` (e.g. `myai_bot`)
4. BotFather will reply with a **bot token** that looks like `7123456789:AAF...`
5. Save this token — you will need it later

---

## Step 2 — Get a Cerebras API key

1. Go to [cloud.cerebras.ai](https://cloud.cerebras.ai) and sign up (free, no credit card)
2. Verify your email and log in
3. Click your profile icon (top right) → **API Keys**
4. Click **Create new API key**, give it a name
5. Copy the key (looks like `csk-...`)
6. Save it — you will need it later

> **Using a different provider?** Any OpenAI-compatible API works. Set `AI_API_KEY` to your provider's key, `AI_BASE_URL` to their base URL, and `AI_MODEL` to the model name.

---

## Step 3 — Create an Upstash Redis database

1. Go to [upstash.com](https://upstash.com) and sign up (free, no credit card)
2. Click **Create Database**
3. Give it a name, choose the region closest to you, click **Create**
4. On the database page, scroll to **REST API** section
5. Copy the **UPSTASH_REDIS_REST_URL** and **UPSTASH_REDIS_REST_TOKEN**
6. Save both — you will need them later

---

## Step 4 — Set up GitHub and clone the repo

1. Create a [GitHub account](https://github.com) if you don't have one
2. Go to the template repo and click **Fork** (top right) to copy it to your account
3. Clone your fork to your computer:

```bash
git clone https://github.com/<your-username>/telegram-vercel-bot.git
cd telegram-vercel-bot
```

---

## Step 5 — Create a Vercel account and install the CLI

1. Go to [vercel.com](https://vercel.com) and sign up using your GitHub account
2. Install Node.js from [nodejs.org](https://nodejs.org) if you don't have it (required for the Vercel CLI)
3. Install the Vercel CLI:

```bash
npm install -g vercel
```

4. Log in to Vercel from your terminal:

```bash
vercel login
```

Choose **Continue with GitHub** and follow the browser prompt.

---

## Step 6 — Deploy to Vercel

From inside the project folder:

```bash
vercel
```

When prompted:
- **Set up and deploy?** → `Y`
- **Which scope?** → select your account
- **Link to existing project?** → `N`
- **Project name?** → press Enter to accept default
- **In which directory is your code?** → press Enter (`.`)

After it finishes, Vercel will print your project URL, e.g. `https://vercel-telegram-bot.vercel.app`. Save this URL.

---

## Step 7 — Add environment variables to Vercel

Run each command below and paste the corresponding value when prompted:

```bash
vercel env add TELEGRAM_BOT_TOKEN
vercel env add AI_API_KEY
vercel env add UPSTASH_REDIS_REST_URL
vercel env add UPSTASH_REDIS_REST_TOKEN
```

For each one, select **Production**, **Preview**, and **Development** when asked which environments to apply to.

Then redeploy to apply the variables:

```bash
vercel --prod
```

---

## Step 7b — Enable web search *(optional)*

The bot can search the web automatically when it needs current information.

1. Go to [tavily.com](https://tavily.com) and sign up (free, no credit card)
2. Click **API Keys** → **Create API Key**
3. Copy the key and add it to Vercel:

```bash
vercel env add TAVILY_API_KEY --value "your_key_here" --force --yes
vercel --prod
```

Safe search is always set to **strict**. Without this key the bot works normally — web search is simply disabled.

When search is used, the bot appends a **Sources:** section with links to every page it used. Results are cached for 10 minutes, so repeated questions don't burn your quota.

---

## Step 7c — Secure the webhook *(optional but recommended)*

Without this, anyone who knows your webhook URL can send fake messages to your bot.

1. Generate a random secret (any string works, e.g. `openssl rand -hex 16`)
2. Add it to Vercel:

```bash
vercel env add WEBHOOK_SECRET --value "your_random_secret" --force --yes
vercel --prod
```

3. Re-register the webhook, appending `&secret_token=your_random_secret`:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/webhook&secret_token=your_random_secret"
```

The bot will now reject any request that does not include the correct secret header.

---

## Step 8 — Register the Telegram webhook

This tells Telegram where to send messages. Run the command below, replacing the placeholders:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/webhook"
```

Example:
```bash
curl "https://api.telegram.org/bot7123456789:AAF.../setWebhook?url=https://vercel-telegram-bot.vercel.app/api/webhook"
```

You should see: `{"ok":true,"result":true}`

**Your bot is now live.** Open Telegram, find your bot, and send it a message.

---

## Project structure

```
telegram-vercel-bot/
├── api/
│   └── index.py          # Entry point — Flask app, webhook route, secret verification
├── bot/
│   ├── config.py         # All env vars and constants
│   ├── clients.py        # bot, ai, redis instances
│   ├── ai.py             # ask_ai orchestration — history, web search injection, source citations
│   ├── providers.py      # Provider dispatch: OpenAI-compatible (with retry) or HF Gradio space
│   ├── preferences.py    # Per-user provider preference stored in Redis
│   ├── search.py         # Tavily web search with Redis result caching
│   ├── history.py        # Conversation memory (Redis, graceful degradation)
│   ├── rate_limit.py     # Per-user rate limiting (graceful degradation)
│   ├── helpers.py        # Utilities (send_reply, keep_typing, should_respond)
│   └── handlers.py       # Telegram commands — add new commands here
├── tests/
│   ├── conftest.py       # Mocks for running tests without real API keys
│   ├── test_ai.py
│   ├── test_providers.py
│   ├── test_preferences.py
│   ├── test_handlers.py
│   ├── test_helpers.py
│   ├── test_history.py
│   ├── test_rate_limit.py
│   ├── test_search.py
│   └── test_webhook.py
├── .github/
│   └── workflows/
│       └── ci.yml        # Runs tests on every push and pull request
├── .env.example          # Copy to .env for local dev (never commit .env)
├── .gitignore
├── Makefile              # install / test / deploy shortcuts
├── requirements.txt
├── vercel.json
├── CLAUDE.md             # Agent-readable project guide
└── README.md
```

---

## Local development

```bash
make install             # creates .venv and installs dependencies
cp .env.example .env     # fill in your real values
.venv/bin/flask --app api/index run --port 3000
```

To test with Telegram locally, install [ngrok](https://ngrok.com), then:

```bash
ngrok http 3000
```

Copy the `https://...ngrok-free.app` URL and re-run the `setWebhook` curl from Step 8 with that URL instead.

---

## Customisation

| What to change | How |
|---|---|
| Bot personality / instructions | Edit `SYSTEM_PROMPT` in `bot/config.py` |
| AI model | Set `AI_MODEL` env var (e.g. `llama3.1-8b`, `gpt-oss-120b`) |
| AI provider | Set `AI_BASE_URL` env var (any OpenAI-compatible endpoint) |
| Enable web search | Set `TAVILY_API_KEY` env var (from tavily.com) |
| Secure the webhook | Set `WEBHOOK_SECRET` env var (see Step 7c) |
| Daily message limit | Set `RATE_LIMIT` env var (default `250`) |
| Add a second provider | Set `HF_SPACE_ID` env var to a Hugging Face Gradio space — enables `/model` command so users can switch. `HF_TOKEN` is only needed for private/gated spaces |
| Conversation memory length | Edit `MAX_HISTORY` in `bot/config.py` |
| Add a new command | Add a handler in `bot/handlers.py` |

---

## Running tests locally

```bash
make install   # set up virtual environment and install dependencies
make test      # run all tests
make deploy    # deploy to Vercel production
```

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/reset` | Clear your conversation history |
| `/about` | Show model and hosting info |
| `/model` | Switch AI provider (only available when `HF_SPACE_ID` is set) |
