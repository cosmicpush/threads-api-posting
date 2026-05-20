from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"


class B2StorageError(RuntimeError):
    """Raised when a Backblaze B2 interaction fails."""


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"b2://{self.bucket}/{self.key}"


@contextmanager
def _wrap_botocore_errors() -> Iterator[None]:
    try:
        yield
    except (BotoCoreError, ClientError) as exc:
        raise B2StorageError(str(exc)) from exc


def _discover_s3_endpoint(key_id: str, application_key: str) -> str:
    try:
        response = requests.get(
            B2_AUTHORIZE_URL,
            auth=(key_id, application_key),
            timeout=30,
        )
    except requests.RequestException as exc:
        raise B2StorageError(f"Failed to reach B2 authorize endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise B2StorageError(
            f"B2 authorize failed ({response.status_code}): {response.text[:200]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise B2StorageError("B2 authorize response was not JSON") from exc

    storage_api = (data.get("apiInfo") or {}).get("storageApi") or {}
    s3_endpoint = storage_api.get("s3ApiUrl") or data.get("s3ApiUrl")
    if not s3_endpoint:
        raise B2StorageError("B2 authorize response did not include s3ApiUrl")

    return s3_endpoint


class B2StorageClient:
    def __init__(self, key_id: str, application_key: str) -> None:
        self.endpoint = _discover_s3_endpoint(key_id, application_key)
        with _wrap_botocore_errors():
            self.client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=key_id,
                aws_secret_access_key=application_key,
                config=Config(signature_version="s3v4"),
            )

    def object_exists(self, obj: ObjectRef) -> bool:
        try:
            self.client.head_object(Bucket=obj.bucket, Key=obj.key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            raise B2StorageError(str(exc)) from exc
        except BotoCoreError as exc:
            raise B2StorageError(str(exc)) from exc

    def generate_presigned_url(self, obj: ObjectRef, expires_in_seconds: int) -> str:
        with _wrap_botocore_errors():
            return self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": obj.bucket, "Key": obj.key},
                ExpiresIn=max(expires_in_seconds, 1),
            )

    def purge_object_versions(self, obj: ObjectRef) -> int:
        # B2 buckets are versioned by default. A bare delete_object only adds a
        # hide/delete marker — the actual versions stick around (up to a couple
        # of days even with keepOnlyLastVersion). Enumerate every version of
        # this exact key and delete each by VersionId for a true hard purge.
        paginator = self.client.get_paginator("list_object_versions")
        to_delete: list[dict] = []

        with _wrap_botocore_errors():
            for page in paginator.paginate(Bucket=obj.bucket, Prefix=obj.key):
                for version in page.get("Versions", []) or []:
                    if version.get("Key") == obj.key and version.get("VersionId"):
                        to_delete.append(
                            {"Key": version["Key"], "VersionId": version["VersionId"]}
                        )
                for marker in page.get("DeleteMarkers", []) or []:
                    if marker.get("Key") == obj.key and marker.get("VersionId"):
                        to_delete.append(
                            {"Key": marker["Key"], "VersionId": marker["VersionId"]}
                        )

        if not to_delete:
            return 0

        removed = 0
        with _wrap_botocore_errors():
            for i in range(0, len(to_delete), 1000):
                chunk = to_delete[i : i + 1000]
                response = self.client.delete_objects(
                    Bucket=obj.bucket,
                    Delete={"Objects": chunk, "Quiet": True},
                )
                errors = response.get("Errors") or []
                if errors:
                    first = errors[0]
                    raise B2StorageError(
                        f"Failed to delete version {first.get('VersionId')} of "
                        f"{first.get('Key')}: {first.get('Message')}"
                    )
                removed += len(chunk)

        return removed
