import io
import logging
import uuid
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings

logger = logging.getLogger(__name__)

_S3_CONFIG = Config(signature_version="s3v4", s3={"addressing_style": "path"})


@lru_cache
def _client(endpoint: str):
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=_S3_CONFIG,
    )


def _internal_client():
    """Client for server-side operations: reachable from inside the network."""
    return _client(get_settings().s3_endpoint_url)


def _signing_client():
    """Client whose endpoint is baked into presigned URLs.

    Signed against the *public* endpoint, because the browser resolves the URL,
    not the backend. Signing does no network I/O, so an unreachable host is fine.
    """
    return _client(get_settings().s3_public_endpoint_url)


def build_key(prefix: str, filename: str) -> str:
    """Namespaced, collision-proof object key that preserves the original name."""
    safe = filename.replace("/", "_").strip() or "file"
    return f"{prefix}/{uuid.uuid4()}/{safe}"


async def ensure_bucket() -> None:
    """Create the bucket if it is missing.

    infra/docker-compose.yml already does this via minio-init; this covers the
    case of the backend running against a bucket-less MinIO (e.g. on the host).
    """
    s = get_settings()

    def _ensure() -> None:
        client = _internal_client()
        try:
            client.head_bucket(Bucket=s.s3_bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code not in ("404", "NoSuchBucket", "403"):
                raise
            if code == "403":
                logger.warning("Bucket %s exists but is not accessible", s.s3_bucket)
                return
            client.create_bucket(Bucket=s.s3_bucket)
            logger.info("Created bucket %s", s.s3_bucket)

    await run_in_threadpool(_ensure)


async def put_object(key: str, data: bytes, content_type: str) -> None:
    s = get_settings()

    def _put() -> None:
        _internal_client().put_object(
            Bucket=s.s3_bucket, Key=key, Body=io.BytesIO(data), ContentType=content_type
        )

    await run_in_threadpool(_put)


async def get_object(key: str) -> bytes:
    s = get_settings()

    def _get() -> bytes:
        response = _internal_client().get_object(Bucket=s.s3_bucket, Key=key)
        return response["Body"].read()

    return await run_in_threadpool(_get)


async def delete_object(key: str) -> None:
    s = get_settings()

    def _delete() -> None:
        _internal_client().delete_object(Bucket=s.s3_bucket, Key=key)

    await run_in_threadpool(_delete)


async def presigned_download_url(key: str, filename: str) -> tuple[str, int]:
    """Time-limited GET URL, with a Content-Disposition that restores the filename."""
    s = get_settings()

    def _sign() -> str:
        return _signing_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": s.s3_bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=s.presign_ttl_seconds,
        )

    url = await run_in_threadpool(_sign)
    return url, s.presign_ttl_seconds
