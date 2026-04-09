import json
from bot.clients import redis
from bot.config import MAX_HISTORY, HISTORY_TTL


def get_history(user_id: int) -> list:
    if redis is None:
        return []
    try:
        data = redis.get(f"chat:{user_id}")
        return json.loads(data) if data else []
    except Exception as e:
        print(f"Redis read error (history): {e}")
        return []


def save_history(user_id: int, history: list) -> None:
    if redis is None:
        return
    try:
        redis.set(f"chat:{user_id}", json.dumps(history[-MAX_HISTORY:]), ex=HISTORY_TTL)
    except Exception as e:
        print(f"Redis write error (history): {e}")


def clear_history(user_id: int) -> None:
    if redis is None:
        return
    try:
        redis.delete(f"chat:{user_id}")
    except Exception as e:
        print(f"Redis delete error (history): {e}")
