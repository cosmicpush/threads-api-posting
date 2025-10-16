import base64
import logging
from typing import Protocol

import requests
from anthropic import Anthropic, APIError

logger = logging.getLogger(__name__)


class ClaudeCaptionError(RuntimeError):
    """Raised when caption generation fails."""


class ClaudeConfig(Protocol):
    anthropic_api_key: str
    claude_model: str
    claude_max_tokens: int
    caption_fallback: str


def _download_image_bytes(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise ClaudeCaptionError(f"Failed to download image for captioning: {exc}") from exc

    if response.status_code >= 400:
        raise ClaudeCaptionError(
            f"Image download failed with status {response.status_code}: {response.text[:200]}"
        )
    return response.content


def _build_prompt() -> str:
    return (
        "You are a social media copywriter for Threads. "
        "Study the quote shown in the image and craft a single-line caption that resonates with it. "
        "Keep it under 18 words, use smart rich text (emojis, emphasis) sparingly but effectively, "
        "and avoid hashtags, quotation marks, or references to the analysis process. "
        "Respond with caption text only."
    )


def generate_caption(config: ClaudeConfig, image_url: str) -> str:
    image_bytes = _download_image_bytes(image_url)
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    client = Anthropic(api_key=config.anthropic_api_key)

    try:
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=config.claude_max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _build_prompt()},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded_image,
                            },
                        },
                    ],
                }
            ],
        )
    except APIError as exc:
        logger.error("Claude API request failed: %s", exc)
        raise ClaudeCaptionError("Claude API call failed") from exc

    caption_parts = [
        block.text.strip()
        for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
    ]

    caption = " ".join(caption_parts).strip()
    if not caption:
        logger.warning("Claude returned no text content; using fallback caption")
        return config.caption_fallback

    return caption
