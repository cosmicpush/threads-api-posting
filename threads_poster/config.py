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


@dataclass(frozen=True)
class Settings:
    threads_access_token: str
    threads_user_id: str
    s3_bucket: str
    s3_prefix: Optional[str]
    media_wait_seconds: int
    presign_expiration_seconds: int
    anthropic_api_key: str
    claude_model: str
    claude_max_tokens: int
    caption_fallback: str


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

    return Settings(
        threads_access_token=_get_env("THREADS_ACCESS_TOKEN"),
        threads_user_id=_get_env("THREADS_USER_ID"),
        s3_bucket=_get_env("THREADS_S3_BUCKET"),
        s3_prefix=os.environ.get("THREADS_S3_PREFIX") or None,
        media_wait_seconds=wait_seconds,
        presign_expiration_seconds=presign_expiration_seconds,
        anthropic_api_key=_get_env("ANTHROPIC_API_KEY"),
        claude_model=os.environ.get("THREADS_CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
        claude_max_tokens=claude_max_tokens,
        caption_fallback=caption_fallback,
    )
