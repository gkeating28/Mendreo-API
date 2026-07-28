import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from . import Api

logger = logging.getLogger(__name__)

# Chat logs contain consumer PII and always go in the private bucket (see
# api/utils/Api.py). Supabase Storage's S3 gateway also requires path-style
# addressing, same as api/utils/File.py.
BUCKET_NAME = Api.SUPABASE_STORAGE_PRIVATE_BUCKET

s3_client = boto3.client(
    's3',
    aws_access_key_id=Api.SUPABASE_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=Api.SUPABASE_STORAGE_SECRET_ACCESS_KEY,
    region_name=Api.SUPABASE_STORAGE_REGION,
    config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    endpoint_url=Api.SUPABASE_STORAGE_S3_ENDPOINT,
)


def upload_text(key: str, text: str):
    """Upload plain text (overwrites existing). Bucket privacy is enforced
    at the bucket level in Supabase (see BUCKET_NAME) -- unlike AWS S3,
    Supabase's S3 gateway doesn't support per-object ACLs."""
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain",
    )


def download_text(key: str, return_empty_on_file_not_found: bool = True) -> str:
    """Download plain text from S3."""
    try:
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        return obj["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response["Error"]["Code"] in ["NoSuchKey", "404"]:
            if return_empty_on_file_not_found:
                return ""
            raise FileNotFoundError(f"S3 file not found: {key}")
        raise


def append_to_txt_file(key, lines):
    """Legacy full-file read-rewrite. Prefer ``write_log_chunk`` for new writes."""
    new_block = "\n".join(lines)
    existing_data = download_text(key, return_empty_on_file_not_found=True)
    upload_text(key, existing_data + new_block)


def write_log_chunk(key: str, lines) -> None:
    """Write a chat-log chunk with a single PUT (no read-modify-write).

    Keys should be unique per session/day so concurrent appends do not race
    and cost stays O(chunk) instead of O(full history).
    """
    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"
    upload_text(key, body)
