import json
import random
import subprocess
from dataclasses import dataclass
from typing import List, Optional


class S3OperationError(RuntimeError):
    """Raised when an AWS CLI command fails."""


@dataclass(frozen=True)
class S3Object:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def _run_aws_cli(args: List[str]) -> str:
    """Run an AWS CLI command and return stdout, raising on failure."""
    result = subprocess.run(
        ["aws", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S3OperationError(result.stderr.strip() or "AWS CLI command failed")
    return result.stdout.strip()


def list_png_objects(bucket: str, prefix: Optional[str] = None) -> List[S3Object]:
    """Return all PNG objects from the bucket (and optional prefix)."""
    args = [
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--query",
        "Contents[].Key",
        "--output",
        "json",
    ]
    if prefix:
        args.extend(["--prefix", prefix])

    stdout = _run_aws_cli(args)
    if not stdout:
        return []

    try:
        keys = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise S3OperationError("Failed to parse AWS CLI output as JSON") from exc

    return [S3Object(bucket=bucket, key=key) for key in keys if key.lower().endswith(".png")]


def choose_random_object(objects: List[S3Object]) -> S3Object:
    if not objects:
        raise S3OperationError("No PNG files found in the specified S3 location")
    return random.choice(objects)


def generate_presigned_url(obj: S3Object, expires_in: int) -> str:
    stdout = _run_aws_cli(
        [
            "s3",
            "presign",
            obj.uri,
            "--expires-in",
            str(expires_in),
        ]
    )
    if not stdout:
        raise S3OperationError(f"Failed to generate presigned URL for {obj.uri}")
    return stdout


def delete_object(obj: S3Object) -> None:
    _run_aws_cli(["s3", "rm", obj.uri])
