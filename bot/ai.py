from bot.config import SYSTEM_PROMPT
from bot.history import get_history, save_history
from bot.providers import generate



# Example of how you might restructure it if you have a specific function for general content
def ask_ai(user_id, prompt, mode="coding"):
    if mode == "creative":
        # Use a system prompt that allows for facts and quotes
        system_prompt = "You are a helpful assistant who can provide facts, motivation, and friendly conversation."
    else:
        # The default prompt you likely have now
        system_prompt = "You are a coding expert. Only answer programming questions."

    # ... rest of your API call logic ...
