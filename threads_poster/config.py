import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    threads_access_token: str
    threads_user_id: str
    bucket: str
    object_prefix: Optional[str]
    b2_key_id: str
    b2_application_key: str
    quotes_json_path: str
    media_wait_seconds: int
    presign_expiration_seconds: int
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    if load_dotenv:
        load_dotenv()

    wait_seconds = int(os.environ.get("THREADS_MEDIA_WAIT_SECONDS", "30"))
    presign_expiration_seconds = int(
        os.environ.get("THREADS_PRESIGN_EXPIRATION_SECONDS", "900")
    )

    return Settings(
        threads_access_token=_get_env("THREADS_ACCESS_TOKEN"),
        threads_user_id=_get_env("THREADS_USER_ID"),
        bucket=_get_env("B2_BUCKET"),
        object_prefix=os.environ.get("B2_PREFIX") or None,
        b2_key_id=_get_env("B2_KEY_ID"),
        b2_application_key=_get_env("B2_APPLICATION_KEY"),
        quotes_json_path=_get_env("QUOTES_JSON_PATH"),
        media_wait_seconds=wait_seconds,
        presign_expiration_seconds=presign_expiration_seconds,
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
    )
