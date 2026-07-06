import os
import json 
import random
from datetime import datetime
from bot.clients import bot, BOT_INFO, store
from bot.config import COMMIT_SHA, HF_SPACE_ID, HOSTING_LABEL, MODEL, RATE_LIMIT
from bot.ai import ask_ai
from bot.providers import generate
from bot.helpers import is_allowed, keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.preferences import get_provider, set_provider
from bot.rate_limit import is_rate_limited

# Verbose console logging for local dev and teaching. Enabled by
# BOT_VERBOSE_LOG=1 (run_local.py sets this automatically). Prints one
# line per inbound/outbound message so kids and teachers can see the
# conversation flow in their terminal while the bot is running.
VERBOSE_LOG = os.environ.get("BOT_VERBOSE_LOG", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _log(message, direction: str, text: str) -> None:
    """Print a one-line trace of a message in verbose mode.

    direction is "in" (user → bot) or "out" (bot → user). Text is
    truncated to 500 characters so long AI replies don't flood the
    terminal. Newlines are collapsed for single-line readability.
    """
    if not VERBOSE_LOG:
        return
    user = message.from_user
    user_name = (
        f"@{user.username}" if user.username else (user.first_name or f"user:{user.id}")
    )
    bot_name = f"@{BOT_INFO.username}"
    snippet = (text or "").replace("\n", " ").replace("\r", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    if direction == "in":
        sender, receiver = user_name, bot_name
    else:
        sender, receiver = bot_name, user_name
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sender} → {receiver}: {snippet}", flush=True)


def _load_notes(user_id):
    """Return the user's saved notes as a list of strings.

    Reads the JSON-encoded list stored under ``note:{user_id}``. Returns
    an empty list in stateless mode (``store is None``), when no notes
    exist yet, or if the stored value is missing/corrupt — so callers can
    always ``.append()`` safely.
    """
    if store is None:
        return []
    try:
        raw = store.get(f"note:{user_id}")
    except Exception as e:
        print(f"Error loading notes: {e}")
        return []
    if not raw:
        return []
    try:
        notes = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return notes if isinstance(notes, list) else []


@bot.message_handler(commands=["start"], func=is_allowed)
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "Hi! I'm your friendly AI assistant bot. I can help you with programming and questions, tell jokes, share motivational quotes, and more. Type /help to see what I can do!",
    )

@bot.message_handler(commands=["joke"], func=is_allowed)
def cmd_joke(message):
 reply = generate(message.from_user.id, [{"role": "user", "content": "Tell one short, clean programming joke."}])
 bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["quote"], func=is_allowed)
def cmd_quote(message):
    reply = generate(
        message.from_user.id,
        [{"role": "user", "content": "Share one original, uplifting motivational line."}],
    )
    bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=["fact"], func=is_allowed)
def cmd_fact(message):
    reply = generate(
        message.from_user.id,
        [{"role": "user", "content": "Tell me one surprising, true fact in a single short sentence."}],
    )
    bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["compliment"], func=is_allowed)
def cmd_compliment(message):
    reply = ask_ai(
        message.from_user.id,
        "Give me one warm, genuine compliment to brighten my day. "
        "Keep it to a single short, uplifting sentence.",
        system_prompt=None,  # trusted command — skip the programming-only filter
    )
    bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["roll"], func=is_allowed)
def cmd_roll(message):
    # The odd one out: no AI call — a plain dice roll in pure Python.
    result = random.randint(1, 6)
    bot.send_message(message.chat.id, f"🎲 You rolled a {result}!")

@bot.message_handler(commands=["roast"], func=is_allowed)
def cmd_roast(message):
 parts = message.text.split(maxsplit=1)
 name = parts[1] if len(parts) > 1 else "you"
 reply = ask_ai(message.from_user.id, f"Write a short, playful, friendly roast of {name}.", system_prompt=None)
 bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=["help"], func=is_allowed)
def cmd_help(message):
    lines = [
        ask_ai(message.from_user.id, "Introduce yourself in two sentences and tell me how you can help me. ", system_prompt=None),
        "",
        "Commands:",
        "/start — start the bot and see a welcome message",
        "/help — show this list of commands",
        "/about — learn more about me",
        "/sha — show the live git commit SHA",
        "/reset — clear our conversation and start fresh",
        "/joke — hear a short programming joke",
        "/quote — get an original motivational line",
        "/fact — learn a surprising fact",
        "/compliment — get a compliment to brighten your day",
        "/roll — roll a six-sided dice",
        "/roast <name> — get a playful roast for yourself or a friend ",
        "/remember <text> — add a note (not replace!)",
        "/recall — show your saved notes",
        "/forget n — delete note number n, or all notes if omitted",
    ]
    if HF_SPACE_ID:
        lines.append("/model — switch AI provider")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")

@bot.message_handler(commands=["remember"], func=is_allowed)
def cmd_remember(message):
 parts = message.text.split(maxsplit=1)
 note = parts[1] if len(parts) > 1 else ""
 notes = _load_notes(message.from_user.id)
 notes.append(note)
 store.set(f"note:{message.from_user.id}", json.dumps(notes))
 bot.send_message(message.chat.id, "Saved!")

@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
 notes = _load_notes(message.from_user.id)
 if notes:
  reply = "\n".join(f"{i}. {n}" for i, n in enumerate(notes, 1))
 else:
  reply = "You have no saved notes yet."
 bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
 # forget         -> delete all notes
 # forget <n>     -> delete just note number n (as shown by /recall)
 notes = _load_notes(message.from_user.id)
 if not notes:
  bot.send_message(message.chat.id, "You have no saved notes to forget.")
  return
 parts = message.text.split(maxsplit=1)
 arg = parts[1].strip() if len(parts) > 1 else ""
 if arg:
  if not arg.isdigit() or not (1 <= int(arg) <= len(notes)):
   bot.send_message(
    message.chat.id,
    f"Please give a note number between 1 and {len(notes)} (see /recall), or use /forget to clear all.",
   )
   return
  removed = notes.pop(int(arg) - 1)
  if store is not None:
   store.set(f"note:{message.from_user.id}", json.dumps(notes))
  bot.send_message(message.chat.id, f"Forgot note: {removed}")
 else:
  if store is not None:
   store.delete(f"note:{message.from_user.id}")
  bot.send_message(message.chat.id, "Forgot all your notes.")


@bot.message_handler(commands=["about"], func=is_allowed)
def cmd_about(message):
    if HF_SPACE_ID:
        provider = get_provider(message.from_user.id)
        model_line = f"{MODEL} (main)" if provider == "main" else f"{HF_SPACE_ID} (hf)"
    else:
        model_line = MODEL
    storage_line = "SQLite" if store is not None else "stateless (no memory)"

    # Ask the AI to introduce itself, generated fresh each time. Uses
    # generate() directly (not ask_ai) so this one-off intro never touches
    # the user's saved conversation history. We deliberately do NOT pass
    # SYSTEM_PROMPT here — otherwise the model parrots those instructions
    # back. Instead we give it a self-contained persona brief, and pick a
    # random angle each call so the intro stays varied and dynamic.
    angles = [
        "Mention a quirky fun fact about how you 'think'.",
        "Frame it like you're meeting a new friend for the first time.",
        "Include a tiny bit of playful humor.",
        "Describe the kinds of questions that excite you most.",
        "Share what your ideal conversation feels like.",
        "Use a warm, encouraging tone like a favorite teacher.",
    ]
    persona_prompt = (
        "You are the friendly AI assistant inside a Telegram bot. In 2-3 short, "
        "lively sentences, introduce yourself to a user: make clear that you are an "
        "AI assistant, and describe your personality and your vibe. Speak in the "
        "first person. Do NOT mention rules, instructions, system prompts, the "
        "underlying model, or other technical details. " + random.choice(angles)
    )
    personality = ""
    try:
        with keep_typing(message.chat.id):
            personality = generate(
                message.from_user.id,
                [{"role": "user", "content": persona_prompt}],
            )
    except Exception as e:
        # Never let a slow/failed AI call break /about — fall back to the
        # technical info below.
        print(f"Error generating /about personality: {e}")

    lines = []
    if personality.strip():
        lines.append(personality.strip())
        lines.append("")
    lines += [
        f"Model  : {model_line}",
        f"Storage: {storage_line}",
        f"Hosting: {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"Version: {COMMIT_SHA}")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["sha"], func=is_allowed)
def cmd_sha(message):
    sha = COMMIT_SHA or "unknown"
    bot.send_message(message.chat.id, f"Live SHA: {sha}")


if HF_SPACE_ID:

    @bot.message_handler(commands=["model"], func=is_allowed)
    def cmd_model(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Current provider: {current}\n\n"
                "Options:\n"
                "/model main — Cerebras (fast, multilingual, with memory)\n"
                "/model hf — ArmGPT (Armenian only, slow, no memory)",
            )
            return
        choice = parts[1].strip().lower()
        if choice not in ("main", "hf"):
            bot.send_message(
                message.chat.id, "Invalid choice. Use: /model main or /model hf"
            )
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(
                message.chat.id, "Could not save preference. Try again later."
            )
            return
        if choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to hf (ArmGPT).\n\n"
                "Note: this is a tiny base completion model trained only on Armenian text. "
                "It will continue whatever you write rather than answer questions, "
                "and it does not understand English. Replies take ~30-60s and there is no memory.",
            )
        else:
            bot.send_message(message.chat.id, "Switched to Main Provider.")


@bot.message_handler(content_types=["text"], func=is_allowed)
def handle_message(message):
    if not should_respond(message):
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    if not text:
        # Edited messages, forwards, or stickers-with-empty-caption can
        # arrive with no usable text. Don't burn rate-limit / AI calls on them.
        return
    _log(message, "in", text)
    if is_rate_limited(message.from_user.id):
        limit_msg = f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow."
        bot.send_message(message.chat.id, limit_msg)
        _log(message, "out", f"[rate limited] {limit_msg}")
        return
    try:
        with keep_typing(message.chat.id):
            reply = ask_ai(message.from_user.id, text)
        send_reply(message, reply)
        _log(message, "out", reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
        _log(message, "out", f"[error] {e}")
