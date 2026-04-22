"""Local fixtures for S3 backend tests (moto-mocked)."""
from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def s3_bucket() -> Iterator[dict[str, str | None]]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        bucket = "pet-ota-test"
        client.create_bucket(Bucket=bucket)
        yield {"bucket": bucket, "endpoint_url": None}
