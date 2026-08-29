import asyncio
import random
import string


def make_id():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


def current_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
