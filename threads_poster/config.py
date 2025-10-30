import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


if load_dotenv:  # pragma: no branch - simple optional load
    # Load variables from a .env file if present
    load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value}")


@dataclass(frozen=True)
class Settings:
    threads_access_token: str
    threads_user_id: str
    bucket: str
    object_prefix: Optional[str]
    media_wait_seconds: int
    presign_expiration_seconds: int
    anthropic_api_key: str
    claude_model: str
    claude_max_tokens: int
    caption_fallback: str
    enable_captioning: bool
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]
    oci_namespace: str
    oci_region: Optional[str]
    oci_profile: Optional[str]


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    wait_seconds = int(os.environ.get("THREADS_MEDIA_WAIT_SECONDS", "30"))
    presign_expiration_seconds = int(os.environ.get("THREADS_PRESIGN_EXPIRATION_SECONDS", "900"))
    claude_max_tokens = int(os.environ.get("THREADS_CLAUDE_MAX_TOKENS", "120"))
    caption_fallback = os.environ.get("THREADS_CAPTION_FALLBACK", "Sharing today's inspiration ✨")
    enable_captioning = _get_bool("THREADS_ENABLE_CAPTIONING", True)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_key = anthropic_key.strip() if anthropic_key else ""
    if enable_captioning and not anthropic_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY must be set when THREADS_ENABLE_CAPTIONING is true"
        )

    bucket = _get_env("THREADS_BUCKET")
    object_prefix = os.environ.get("THREADS_PREFIX") or None

    return Settings(
        threads_access_token=_get_env("THREADS_ACCESS_TOKEN"),
        threads_user_id=_get_env("THREADS_USER_ID"),
        bucket=bucket,
        object_prefix=object_prefix,
        media_wait_seconds=wait_seconds,
        presign_expiration_seconds=presign_expiration_seconds,
        anthropic_api_key=anthropic_key,
        claude_model=os.environ.get("THREADS_CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
        claude_max_tokens=claude_max_tokens,
        caption_fallback=caption_fallback,
        enable_captioning=enable_captioning,
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
        oci_namespace=_get_env("OCI_NAMESPACE"),
        oci_region=os.environ.get("OCI_REGION") or None,
        oci_profile=os.environ.get("OCI_PROFILE") or None,
    )
