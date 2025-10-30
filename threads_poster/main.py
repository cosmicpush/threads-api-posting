import logging
import os
import sys
import time
from typing import Optional

import requests

from .oci_storage import (
    OCIStorageClient,
    OCIStorageError,
    ObjectRef,
    PreauthenticatedRequest,
    choose_random_object,
)
from .claude_caption import ClaudeCaptionError, generate_caption
from .config import load_settings
from .threads_api import (
    ThreadsApiError,
    check_container_status,
    create_media_container,
    get_profile_details,
    publish_container,
)


def _format_threads_label(details: Optional[dict], user_id: str) -> str:
    display_name = details.get("display_name") if details else None
    username = details.get("username") if details else None
    handle = f"@{username}" if username else None

    if display_name and handle:
        return f"{display_name} ({handle})"
    if display_name:
        return display_name
    if handle:
        return handle
    return user_id


def _send_telegram_message(
    bot_token: Optional[str],
    chat_id: Optional[str],
    message: str,
    logger: logging.Logger,
) -> None:
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.warning("Failed to send Telegram notification: %s", exc)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("threads_poster")

    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    try:
        settings = load_settings()
    except (RuntimeError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        _send_telegram_message(
            telegram_bot_token,
            telegram_chat_id,
            "\n".join(
                [
                    "❌ Threads poster failed",
                    f"Error: {exc}",
                ]
            ),
            logger,
        )
        return 1

    telegram_bot_token = settings.telegram_bot_token or telegram_bot_token
    telegram_chat_id = settings.telegram_chat_id or telegram_chat_id

    profile_details: Optional[dict] = None
    try:
        profile_details = get_profile_details(
            settings.threads_access_token,
            settings.threads_user_id,
        )
    except ThreadsApiError as exc:
        logger.warning("Failed to fetch Threads profile details: %s", exc)

    account_label = _format_threads_label(profile_details, settings.threads_user_id)

    storage: Optional[OCIStorageClient] = None
    selected_object: Optional[ObjectRef] = None
    caption: Optional[str] = None
    container_id: Optional[str] = None
    thread_id: Optional[str] = None
    last_error: Optional[str] = None
    par_request: Optional[PreauthenticatedRequest] = None

    def finish(result_code: int, *, error: Optional[str] = None) -> int:
        nonlocal par_request

        if par_request and storage:
            try:
                storage.revoke_preauthenticated_request(par_request)
            except OCIStorageError as exc:
                logger.warning("Failed to revoke pre-authenticated request: %s", exc)
            finally:
                par_request = None

        final_error = error or last_error
        if telegram_bot_token and telegram_chat_id:
            heading = (
                "✅ Threads post published"
                if result_code == 0
                else "❌ Threads poster failed"
            )

            lines = [heading, f"Threads Account: {account_label}"]

            if selected_object:
                lines.append(f"Object Key: {selected_object.key}")

            if thread_id:
                lines.append(f"Thread ID: {thread_id}")

            if final_error:
                lines.append(f"Error: {final_error}")

            message = "\n".join(lines)
            _send_telegram_message(telegram_bot_token, telegram_chat_id, message, logger)

        return result_code

    try:
        storage = OCIStorageClient(
            settings.oci_namespace,
            region=settings.oci_region,
            profile=settings.oci_profile,
        )
    except OCIStorageError as exc:
        last_error = str(exc)
        logger.error("Failed to initialize OCI storage client: %s", exc)
        return finish(1, error=str(exc))

    logger.info("Selecting random PNG from bucket %s", settings.bucket)

    try:
        objects = storage.list_png_objects(settings.bucket, settings.object_prefix)
        selected_object = choose_random_object(objects)
        logger.info("Selected %s", selected_object.key)
        par_request = storage.generate_presigned_url(
            selected_object, settings.presign_expiration_seconds
        )
        presigned_url = par_request.url
        logger.info(
            "Generated pre-authenticated URL valid for %s seconds",
            settings.presign_expiration_seconds,
        )
    except OCIStorageError as exc:
        last_error = str(exc)
        logger.error("OCI operation failed: %s", exc)
        return finish(1, error=str(exc))

    if settings.enable_captioning:
        try:
            caption = generate_caption(settings, presigned_url)
            logger.info("Generated caption for %s", selected_object.key)
        except ClaudeCaptionError as exc:
            logger.error("Failed to generate caption via Claude: %s", exc)
            caption = ""
            logger.info("Caption generation failed; posting without caption")
    else:
        caption = ""
        logger.info("Caption generation disabled; posting without caption")

    try:
        caption_payload = caption or ""

        container_id = create_media_container(
            settings.threads_access_token,
            settings.threads_user_id,
            presigned_url,
            caption_payload,
        )
        logger.info("Created media container %s", container_id)
    except ThreadsApiError as exc:
        last_error = str(exc)
        logger.error("Failed to create media container: %s", exc)
        return finish(1, error=str(exc))

    wait_seconds = max(settings.media_wait_seconds, 0)
    if wait_seconds:
        logger.info("Waiting %s seconds for media processing", wait_seconds)
        time.sleep(wait_seconds)

    try:
        status = check_container_status(settings.threads_access_token, container_id)
    except ThreadsApiError as exc:
        logger.warning("Could not confirm container status: %s", exc)
        status = None

    if status:
        logger.info("Container status: %s", status)

    try:
        thread_id = publish_container(
            settings.threads_access_token,
            settings.threads_user_id,
            container_id,
        )
        logger.info("Published thread %s", thread_id)
    except ThreadsApiError as exc:
        last_error = str(exc)
        logger.error("Failed to publish container: %s", exc)
        return finish(1, error=str(exc))

    try:
        storage.delete_object(selected_object)
        logger.info(
            "Deleted %s from bucket %s",
            selected_object.key,
            settings.bucket,
        )
    except OCIStorageError as exc:
        logger.warning(
            "Thread posted but failed to delete %s: %s",
            selected_object.uri,
            exc,
        )

    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
