from datetime import date
from bot.clients import redis
from bot.config import RATE_LIMIT


def is_rate_limited(user_id: int) -> bool:
    if redis is None:
        return False  # no rate limiting in stateless mode
    try:
        key = f"rate:{user_id}:{date.today()}"
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, 86400)  # reset after 24 hours
        return count > RATE_LIMIT
    except Exception as e:
        print(f"Redis error (rate_limit): {e}")
        return False  # allow messages when Redis is down
