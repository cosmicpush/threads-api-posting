import fcntl
import logging
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import requests

from .b2_storage import B2StorageClient, B2StorageError, ObjectRef
from .config import load_settings
from .quotes_store import QuoteEntry, QuotesStore, QuotesStoreError
from .threads_api import (
    ThreadsApiError,
    check_container_status,
    create_media_container,
    get_profile_details,
    publish_container,
)

logger = logging.getLogger("threads_poster")

DEFAULT_LOCKFILE_PATH = os.path.join(tempfile.gettempdir(), "threads_poster.lock")


class _StepFailed(Exception):
    """Internal sentinel raised by `_step` to bail out of the pipeline."""


@contextmanager
def _step(label: str) -> Iterator[None]:
    try:
        yield
    except (B2StorageError, ThreadsApiError, QuotesStoreError) as exc:
        logger.error("%s failed: %s", label, exc)
        raise _StepFailed(str(exc)) from exc


def _format_threads_label(details: Optional[dict], user_id: str) -> str:
    name = details.get("name") if details else None
    username = details.get("username") if details else None
    handle = f"@{username}" if username else None

    if name and handle:
        return f"{name} ({handle})"
    if name:
        return name
    if handle:
        return handle
    return user_id


def _send_telegram_message(
    bot_token: Optional[str],
    chat_id: Optional[str],
    message: str,
) -> None:
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.warning("Failed to send Telegram notification: %s", exc)


def _build_object_key(prefix: Optional[str], image: str) -> str:
    if not prefix:
        return image
    if prefix.endswith("/"):
        return f"{prefix}{image}"
    return f"{prefix}/{image}"


@contextmanager
def _exclusive_lock(path: str) -> Iterator[bool]:
    # Non-blocking flock — yields True if acquired, False if another instance
    # already holds it. POSIX-only; fine for the Docker base image used here.
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    lockfile_path = os.environ.get("LOCKFILE_PATH") or DEFAULT_LOCKFILE_PATH

    with _exclusive_lock(lockfile_path) as acquired:
        if not acquired:
            logger.warning(
                "Another threads_poster instance is running (lockfile %s); exiting",
                lockfile_path,
            )
            return 0
        return _run(telegram_bot_token, telegram_chat_id)


def _run(
    telegram_bot_token: Optional[str],
    telegram_chat_id: Optional[str],
) -> int:
    try:
        settings = load_settings()
    except (RuntimeError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        _send_telegram_message(
            telegram_bot_token,
            telegram_chat_id,
            "\n".join(["❌ Threads poster failed", f"Error: {exc}"]),
        )
        return 1

    telegram_bot_token = settings.telegram_bot_token
    telegram_chat_id = settings.telegram_chat_id

    profile_details: Optional[dict] = None
    try:
        profile_details = get_profile_details(
            settings.threads_access_token,
            settings.threads_user_id,
        )
    except ThreadsApiError as exc:
        logger.warning("Failed to fetch Threads profile details: %s", exc)

    account_label = _format_threads_label(profile_details, settings.threads_user_id)

    selected_entry: Optional[QuoteEntry] = None
    selected_object: Optional[ObjectRef] = None
    thread_id: Optional[str] = None
    last_error: Optional[str] = None

    def finish(result_code: int, *, error: Optional[str] = None) -> int:
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
            _send_telegram_message(telegram_bot_token, telegram_chat_id, "\n".join(lines))
        return result_code

    quotes = QuotesStore(settings.quotes_json_path)

    try:
        with _step("Pick quote entry"):
            selected_entry = quotes.pick_random()
        logger.info("Selected quote entry for image %s", selected_entry.image)

        with _step("Initialize B2 storage client"):
            storage = B2StorageClient(settings.b2_key_id, settings.b2_application_key)

        key = _build_object_key(settings.object_prefix, selected_entry.image)
        selected_object = ObjectRef(bucket=settings.bucket, key=key)

        with _step("Check image in B2"):
            exists = storage.object_exists(selected_object)

        if not exists:
            logger.warning(
                "Image %s referenced in quotes.json is missing from B2; pruning stale entry",
                selected_object.uri,
            )
            try:
                quotes.remove(selected_entry)
            except QuotesStoreError as exc:
                logger.warning("Failed to prune stale quotes entry: %s", exc)
            return finish(1, error=f"Image missing in B2: {selected_object.key}")

        with _step("Generate presigned URL"):
            presigned_url = storage.generate_presigned_url(
                selected_object, settings.presign_expiration_seconds
            )
        logger.info(
            "Generated presigned URL valid for %s seconds",
            settings.presign_expiration_seconds,
        )

        with _step("Create media container"):
            container_id = create_media_container(
                settings.threads_access_token,
                settings.threads_user_id,
                presigned_url,
                selected_entry.caption,
            )
        logger.info("Created media container %s", container_id)

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

        with _step("Publish container"):
            thread_id = publish_container(
                settings.threads_access_token,
                settings.threads_user_id,
                container_id,
            )
        logger.info("Published thread %s", thread_id)

    except _StepFailed as exc:
        last_error = str(exc)
        return finish(1, error=last_error)

    # Post is live. From here on, failures only produce warnings — the
    # entry has effectively been consumed.
    try:
        quotes.remove(selected_entry)
        logger.info("Removed entry for %s from quotes file", selected_entry.image)
    except QuotesStoreError as exc:
        logger.warning("Thread posted but failed to update quotes file: %s", exc)

    try:
        removed = storage.purge_object_versions(selected_object)
        logger.info(
            "Purged %s version(s) of %s from bucket %s",
            removed,
            selected_object.key,
            settings.bucket,
        )
    except B2StorageError as exc:
        logger.warning(
            "Thread posted but failed to purge %s: %s",
            selected_object.uri,
            exc,
        )

    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
