from bot.config import SYSTEM_PROMPT
from bot.history import get_history, save_history
from bot.providers import generate


def ask_ai(user_id: int, user_message: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    """Answer a user turn, with conversation memory and a system prompt.

    ``system_prompt`` defaults to the restrictive programming-only prompt used
    for free-form chat. Trusted command handlers (e.g. /roast, /compliment,
    /help) that generate non-programming content pass ``system_prompt=None`` so
    the programming-only filter does NOT reject them — those commands are gated
    by the telebot handler, not by the model, and never reach here as raw slash
    commands anyway (Telegram routes them to their handler first).
    """
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages += history

    reply = generate(user_id, messages)

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)
    return reply


