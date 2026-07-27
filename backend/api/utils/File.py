import logging
import os

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

from . import Api, Constants

# set boto lib debug to critical
logging.getLogger("boto").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# Object storage lives on Supabase Storage. Browser uploads use Supabase's
# native signed-upload URLs (REST) because S3-compatible presigns for this
# project return SignatureDoesNotMatch with the configured S3 access keys.
# boto3 remains as a fallback for local/CI stubs and private-bucket helpers.
s3 = boto3.client(
    "s3",
    aws_access_key_id=Api.SUPABASE_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=Api.SUPABASE_STORAGE_SECRET_ACCESS_KEY,
    region_name=Api.SUPABASE_STORAGE_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    endpoint_url=Api.SUPABASE_STORAGE_S3_ENDPOINT,
)

IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg"]

# Browser File.type values the Content Editor will send on PUT.
_EXTENSION_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "json": "application/json",
}


def content_type_for_path(path: str) -> str:
    """Return the Content-Type browsers typically use for this file extension."""
    _, ext = os.path.splitext(path or "")
    ext = ext.lstrip(".").lower()
    return _EXTENSION_CONTENT_TYPES.get(ext, "application/octet-stream")


def _storage_key() -> str:
    """Prefer service role (bypasses RLS); fall back to anon (needs policies)."""
    return Api.SUPABASE_SERVICE_ROLE_KEY or Api.SUPABASE_ANON_KEY


def _storage_headers() -> dict:
    key = _storage_key()
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }


def _rest_enabled() -> bool:
    return bool(Api.SUPABASE_STORAGE_URL and _storage_key() and Api.SUPABASE_STORAGE_BUCKET)


def upload(data, full_path, content_type=None, public=True):
    key = _get_key(full_path)
    if _rest_enabled():
        try:
            _rest_upload(key, data, content_type)
            return
        except Exception as error:
            logger.warning("REST upload failed, falling back to S3: %s", error)

    try:
        params = {
            "Bucket": Api.SUPABASE_STORAGE_BUCKET,
            "Key": key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        s3.put_object(**params)
    except Exception as error:
        print(error)
        return "Upload error: {}".format(error)


def get_extension(file):
    ext = file.name.split(".")
    return ext[len(ext) - 1].lower()


def get_image_extension(file):
    allowed_extensions = Constants.IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS

    ext = file.name.split(".")

    if ext[len(ext) - 1].lower() in allowed_extensions:
        return ext[len(ext) - 1].lower()
    else:
        return "jpg"


def get_upload_link(path, content_type=None):
    """Return (upload_url, content_type) for a browser PUT.

    Prefer Supabase REST signed upload URLs. Fall back to S3 presigns when
    REST credentials are unavailable (e.g. local unit tests with stub env).
    """
    if content_type is None:
        content_type = content_type_for_path(path)

    key = _get_key(path)

    if _rest_enabled():
        try:
            return _rest_signed_upload_link(key), content_type
        except Exception as error:
            logger.warning("REST signed upload URL failed, falling back to S3: %s", error)

    return _s3_presigned_upload_link(key, content_type), content_type


def _rest_signed_upload_link(key: str) -> str:
    """Create a time-limited Supabase Storage signed upload URL."""
    url = (
        f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/upload/sign/"
        f"{Api.SUPABASE_STORAGE_BUCKET}/{key}"
    )
    response = requests.post(url, headers=_storage_headers(), timeout=30)
    response.raise_for_status()
    payload = response.json()
    relative = payload.get("url") or payload.get("signedUrl") or payload.get("signedURL")
    if not relative:
        raise RuntimeError(f"Supabase signed upload response missing url: {payload}")

    if relative.startswith("http://") or relative.startswith("https://"):
        return relative
    if not relative.startswith("/"):
        relative = "/" + relative
    # API returns paths like /object/upload/sign/...?token=...
    if relative.startswith("/storage/v1/"):
        return f"{Api.SUPABASE_STORAGE_URL}{relative}"
    return f"{Api.SUPABASE_STORAGE_URL}/storage/v1{relative}"


def _s3_presigned_upload_link(key: str, content_type: str) -> str:
    params = {
        "Bucket": Api.SUPABASE_STORAGE_BUCKET,
        "Key": key,
        "ContentType": content_type,
    }
    return s3.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=3600,
    )


def _rest_upload(key: str, data, content_type=None):
    url = (
        f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
        f"{Api.SUPABASE_STORAGE_BUCKET}/{key}"
    )
    headers = _storage_headers()
    if content_type:
        headers["Content-Type"] = content_type
    headers["x-upsert"] = "true"
    response = requests.post(url, headers=headers, data=data, timeout=60)
    response.raise_for_status()


def delete(file_url):
    if not file_url:
        return

    key = _get_key(file_url)

    if _rest_enabled():
        try:
            url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
                f"{Api.SUPABASE_STORAGE_BUCKET}/{key}"
            )
            response = requests.delete(url, headers=_storage_headers(), timeout=30)
            if response.status_code in (200, 404):
                return
            response.raise_for_status()
            return
        except Exception as error:
            logger.warning("REST delete failed, falling back to S3: %s", error)

    response = s3.delete_object(Bucket=Api.SUPABASE_STORAGE_BUCKET, Key=key)

    if response["ResponseMetadata"]["HTTPStatusCode"] == 204:
        print(f"File '{file_url}' deleted successfully from bucket '{Api.SUPABASE_STORAGE_BUCKET}'.")
    else:
        print(f"Failed to delete file '{file_url}' from bucket '{Api.SUPABASE_STORAGE_BUCKET}'.")


def exists(file_url):
    key = _get_key(file_url)

    if _rest_enabled():
        try:
            auth_url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
                f"{Api.SUPABASE_STORAGE_BUCKET}/{key}"
            )
            head = requests.head(auth_url, headers=_storage_headers(), timeout=30)
            if head.status_code == 200:
                return True
            if head.status_code in (400, 404):
                return False
            # Some gateways reject HEAD; try public info endpoint.
            info_url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/info/public/"
                f"{Api.SUPABASE_STORAGE_BUCKET}/{key}"
            )
            info = requests.get(info_url, headers=_storage_headers(), timeout=30)
            return info.status_code == 200
        except Exception as error:
            logger.warning("REST exists check failed, falling back to S3: %s", error)

    try:
        s3.head_object(Bucket=Api.SUPABASE_STORAGE_BUCKET, Key=key)
        return True
    except ClientError:
        return False


def _get_key(path):
    if path.startswith("/"):
        path = path[1:]

    return path
