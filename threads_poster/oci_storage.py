import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import oci
from oci.exceptions import ServiceError
from oci.object_storage.models import CreatePreauthenticatedRequestDetails


class OCIStorageError(RuntimeError):
    """Raised when an OCI Object Storage interaction fails."""


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"oci://{self.bucket}/{self.key}"


@dataclass(frozen=True)
class PreauthenticatedRequest:
    bucket: str
    id: str
    url: str


class OCIStorageClient:
    def __init__(
        self,
        namespace: Optional[str],
        *,
        region: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> None:
        try:
            if profile:
                config = oci.config.from_file(profile_name=profile)
            else:
                config = oci.config.from_file()
        except Exception as exc:  # pragma: no cover - environment specific
            raise OCIStorageError(f"Failed to load OCI configuration: {exc}") from exc

        if region:
            config["region"] = region

        try:
            oci.config.validate_config(config)
        except Exception as exc:  # pragma: no cover - validation should happen once
            raise OCIStorageError(f"Invalid OCI configuration: {exc}") from exc

        self.region = config.get("region")
        if not self.region:
            raise OCIStorageError("OCI configuration is missing a region value")

        try:
            self.client = oci.object_storage.ObjectStorageClient(config)
        except Exception as exc:  # pragma: no cover - network failure
            raise OCIStorageError(f"Failed to create OCI Object Storage client: {exc}") from exc

        if namespace:
            self.namespace = namespace
        else:  # pragma: no cover - namespace should be provided by env
            try:
                self.namespace = self.client.get_namespace().data
            except Exception as exc:
                raise OCIStorageError(f"Failed to resolve OCI namespace: {exc}") from exc

    def list_png_objects(self, bucket: str, prefix: Optional[str] = None) -> List[ObjectRef]:
        try:
            objects: List[ObjectRef] = []
            next_start: Optional[str] = None
            while True:
                kwargs = {"prefix": prefix, "fields": "name"}
                if next_start:
                    kwargs["start"] = next_start

                response = self.client.list_objects(
                    self.namespace,
                    bucket,
                    **kwargs,
                )

                for obj in response.data.objects:
                    name = obj.name or ""
                    if name.lower().endswith(".png"):
                        objects.append(ObjectRef(bucket=bucket, key=name))

                next_start = response.data.next_start_with
                if not next_start:
                    break

            return objects
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc

    def download_object(self, obj: ObjectRef) -> bytes:
        try:
            response = self.client.get_object(self.namespace, obj.bucket, obj.key)
            return response.data.content
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc

    def upload_bytes(self, obj: ObjectRef, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                self.namespace,
                obj.bucket,
                obj.key,
                data,
                content_type=content_type,
            )
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc

    def generate_presigned_url(
        self,
        obj: ObjectRef,
        expires_in_seconds: int,
    ) -> PreauthenticatedRequest:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in_seconds, 1))
        details = CreatePreauthenticatedRequestDetails(
            name=f"temp-par-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            access_type="ObjectRead",
            time_expires=expiry,
            object_name=obj.key,
        )

        try:
            response = self.client.create_preauthenticated_request(
                self.namespace,
                obj.bucket,
                details,
            )
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc

        if not response.data or not response.data.access_uri:
            raise OCIStorageError(f"Failed to create pre-authenticated request for {obj.uri}")

        url = f"https://objectstorage.{self.region}.oraclecloud.com{response.data.access_uri}"
        return PreauthenticatedRequest(bucket=obj.bucket, id=response.data.id, url=url)

    def delete_object(self, obj: ObjectRef) -> None:
        try:
            self.client.delete_object(self.namespace, obj.bucket, obj.key)
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc

    def revoke_preauthenticated_request(self, par: PreauthenticatedRequest) -> None:
        try:
            self.client.delete_preauthenticated_request(
                self.namespace,
                par.bucket,
                par.id,
            )
        except ServiceError as exc:
            raise OCIStorageError(exc.message or str(exc)) from exc
        except Exception as exc:
            raise OCIStorageError(str(exc)) from exc


def choose_random_object(objects: List[ObjectRef]) -> ObjectRef:
    if not objects:
        raise OCIStorageError("No PNG files found in the specified OCI bucket")
    return random.choice(objects)
