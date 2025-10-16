import logging
import sys
import time

from .aws_s3 import (
    S3OperationError,
    choose_random_object,
    delete_object,
    generate_presigned_url,
    list_png_objects,
)
from .claude_caption import ClaudeCaptionError, generate_caption
from .config import load_settings
from .threads_api import (
    ThreadsApiError,
    check_container_status,
    create_media_container,
    publish_container,
)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("threads_poster")

    try:
        settings = load_settings()
    except (RuntimeError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    logger.info("Selecting random PNG from bucket %s", settings.s3_bucket)

    try:
        objects = list_png_objects(settings.s3_bucket, settings.s3_prefix)
        selected_object = choose_random_object(objects)
        logger.info("Selected %s", selected_object.key)
        presigned_url = generate_presigned_url(
            selected_object, settings.presign_expiration_seconds
        )
        logger.info("Generated presigned URL valid for %s seconds", settings.presign_expiration_seconds)
    except S3OperationError as exc:
        logger.error("S3 operation failed: %s", exc)
        return 1

    try:
        caption = generate_caption(settings, presigned_url)
        logger.info("Generated caption for %s", selected_object.key)
    except ClaudeCaptionError as exc:
        logger.error("Failed to generate caption via Claude: %s", exc)
        caption = settings.caption_fallback
        logger.info("Using fallback caption")

    try:
        container_id = create_media_container(
            settings.threads_access_token,
            settings.threads_user_id,
            presigned_url,
            caption,
        )
        logger.info("Created media container %s", container_id)
    except ThreadsApiError as exc:
        logger.error("Failed to create media container: %s", exc)
        return 1

    wait_seconds = max(settings.media_wait_seconds, 0)
    if wait_seconds:
        logger.info("Waiting %s seconds for media processing", wait_seconds)
        time.sleep(wait_seconds)

    status = None
    try:
        status = check_container_status(settings.threads_access_token, container_id)
    except ThreadsApiError as exc:
        logger.warning("Could not confirm container status: %s", exc)

    if status:
        logger.info("Container status: %s", status)

    try:
        thread_id = publish_container(
            settings.threads_access_token, settings.threads_user_id, container_id
        )
        logger.info("Published thread %s", thread_id)
    except ThreadsApiError as exc:
        logger.error("Failed to publish container: %s", exc)
        return 1

    try:
        delete_object(selected_object)
        logger.info("Deleted %s from bucket %s", selected_object.key, settings.s3_bucket)
    except S3OperationError as exc:
        logger.warning(
            "Thread posted but failed to delete %s: %s",
            selected_object.uri,
            exc,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
