import json
from bot.clients import store
from bot.config import MAX_HISTORY, HISTORY_TTL


def get_history(user_id: int) -> list:
    if store is None:
        return []
    try:
        data = store.get(f"chat:{user_id}")
        return json.loads(data) if data else []
    except Exception as e:
        print(f"Store read error (history): {e}")
        return []


def save_history(user_id: int, history: list) -> None:
    if store is None:
        return
    try:
        store.set(
            f"chat:{user_id}",
            json.dumps(history[-MAX_HISTORY:]),
            ex=HISTORY_TTL,
        )
    except Exception as e:
        print(f"Store write error (history): {e}")


def clear_history(user_id: int) -> None:
    if store is None:
        return
    try:
        store.delete(f"chat:{user_id}")
    except Exception as e:
        print(f"Store delete error (history): {e}")
