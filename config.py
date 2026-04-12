import os


def _to_int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        raise RuntimeError("CHAT_ID должен быть числом. Проверь переменную окружения CHAT_ID.")


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = _to_int(os.getenv("CHAT_ID"))
BASE_URL = os.getenv("BASE_URL", "https://sibbp.ru/").strip() or "https://sibbp.ru/"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
