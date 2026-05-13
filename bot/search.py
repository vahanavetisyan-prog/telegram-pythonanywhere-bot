import hashlib
import json
import requests
from bot.clients import store
from bot.config import TAVILY_API_KEY

TAVILY_ENDPOINT = "https://api.tavily.com/search"
CACHE_TTL = 600  # cache results for 10 minutes


def web_search(query: str, count: int = 5) -> tuple[str, list[dict]]:
    """Search the web via Tavily API.

    Returns (formatted_text, sources) where sources is a list of
    {"title": ..., "url": ...} dicts for citation.
    """
    cache_key = f"search:{hashlib.md5(query.lower().encode()).hexdigest()}"
    if store is not None:
        try:
            cached = store.get(cache_key)
            if isinstance(cached, str) and cached:
                data = json.loads(cached)
                return data["text"], data["sources"]
        except Exception as e:
            print(f"Store read error (search cache): {e}")

    response = requests.post(
        TAVILY_ENDPOINT,
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": count,
        },
        timeout=10,
    )
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        return "No results found.", []

    sources = [{"title": r["title"], "url": r["url"]} for r in results]
    formatted = "\n\n".join(
        f"{r['title']}\n{r.get('content', '')}\n{r['url']}" for r in results
    )

    if store is not None:
        try:
            store.set(
                cache_key,
                json.dumps({"text": formatted, "sources": sources}),
                ex=CACHE_TTL,
            )
        except Exception as e:
            print(f"Store write error (search cache): {e}")

    return formatted, sources
