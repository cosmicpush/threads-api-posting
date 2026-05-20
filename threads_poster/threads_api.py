from __future__ import annotations

import logging
from typing import Optional

import requests

THREADS_API_BASE = "https://graph.threads.net/v1.0"

logger = logging.getLogger(__name__)


class ThreadsApiError(RuntimeError):
    """Raised when the Threads Graph API returns an error response."""


def _handle_response(response: requests.Response) -> dict:
    if response.status_code >= 400:
        message: Optional[str] = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            message = (payload.get("error") or {}).get("message")
        if not message:
            message = (response.text or "")[:300] or "no response body"
        raise ThreadsApiError(f"Threads API error ({response.status_code}): {message}")

    try:
        return response.json()
    except ValueError as exc:
        raise ThreadsApiError("Failed to parse Threads API response as JSON") from exc


def _require_field(data: dict, field: str, label: str) -> str:
    value = data.get(field)
    if not value:
        raise ThreadsApiError(f"Threads API response did not include {label}")
    return value


def create_media_container(
    access_token: str,
    user_id: str,
    image_url: str,
    caption: str,
    timeout: int = 30,
) -> str:
    url = f"{THREADS_API_BASE}/{user_id}/threads"
    payload = {
        "media_type": "IMAGE",
        "image_url": image_url,
        "text": caption,
        "access_token": access_token,
    }
    response = requests.post(url, data=payload, timeout=timeout)
    container_id = _require_field(_handle_response(response), "id", "a container ID")
    logger.debug("Created media container %s", container_id)
    return container_id


def publish_container(
    access_token: str,
    user_id: str,
    container_id: str,
    timeout: int = 30,
) -> str:
    url = f"{THREADS_API_BASE}/{user_id}/threads_publish"
    payload = {
        "creation_id": container_id,
        "access_token": access_token,
    }
    response = requests.post(url, data=payload, timeout=timeout)
    thread_id = _require_field(_handle_response(response), "id", "a thread ID")
    logger.debug("Published container %s as thread %s", container_id, thread_id)
    return thread_id


def check_container_status(
    access_token: str,
    container_id: str,
    timeout: int = 30,
) -> Optional[str]:
    url = f"{THREADS_API_BASE}/{container_id}"
    params = {"fields": "status", "access_token": access_token}
    response = requests.get(url, params=params, timeout=timeout)
    data = _handle_response(response)
    status = data.get("status")
    logger.debug("Container %s status %s", container_id, status)
    return status


def get_profile_details(
    access_token: str,
    user_id: str,
    timeout: int = 30,
) -> dict:
    url = f"{THREADS_API_BASE}/{user_id}"
    params = {"fields": "id,username,name", "access_token": access_token}
    response = requests.get(url, params=params, timeout=timeout)
    data = _handle_response(response)
    logger.debug("Fetched Threads profile details for %s: %s", user_id, data)
    return data
