from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.config.logging import get_logger
from src.config.settings import get_settings

logger = get_logger(module="s3_client")

_MAX_RETRIES = 5
_BACKOFF_BASE = 1.0


class S3Client:
    def __init__(self) -> None:
        settings = get_settings()
        kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
            "config": Config(
                retries={"max_attempts": _MAX_RETRIES, "mode": "adaptive"},
                connect_timeout=30,
                read_timeout=300,
            ),
        }
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self._client = boto3.client("s3", **kwargs)
        self._bucket = settings.s3_bucket_name
        self._key = settings.s3_object_key

    def get_object_metadata(self) -> dict[str, str]:
        resp = self._client.head_object(Bucket=self._bucket, Key=self._key)
        return {
            "etag": resp.get("ETag", "").strip('"'),
            "last_modified": str(resp.get("LastModified", "")),
            "content_length": str(resp.get("ContentLength", 0)),
        }

    def stream_object(self, start_byte: int = 0) -> Any:
        """Stream the mbox object from S3, optionally from an offset."""
        range_header = f"bytes={start_byte}-" if start_byte > 0 else None
        kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": self._key}
        if range_header:
            kwargs["Range"] = range_header

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.get_object(**kwargs)
                return resp["Body"]
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("SlowDown", "503", "500", "RequestTimeout"):
                    wait = _BACKOFF_BASE * (2**attempt)
                    logger.warning("s3_retry", attempt=attempt + 1, wait=wait, error=code)
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("S3 streaming failed after max retries")

    def has_changed(self, known_etag: str) -> bool:
        meta = self.get_object_metadata()
        return meta["etag"] != known_etag
