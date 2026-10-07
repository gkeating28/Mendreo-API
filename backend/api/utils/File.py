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
    "md": "text/markdown",
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
            "Bucket": bucket_for_key(key),
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


KNOWLEDGE_FOLDER = "knowledge"


class KnowledgeFileMissing(Exception):
    """The uploaded object cannot be copied into the private knowledge folder."""


def bucket_for_key(path: str) -> str:
    """Knowledge sources live in the private bucket. Other uploads stay public."""
    key = _get_key(path or "")
    if key.startswith(f"{KNOWLEDGE_FOLDER}/"):
        return Api.SUPABASE_STORAGE_PRIVATE_BUCKET or Api.SUPABASE_STORAGE_BUCKET
    return Api.SUPABASE_STORAGE_BUCKET


def get_upload_link(path, content_type=None):
    """Return (upload_url, content_type) for a browser PUT.

    Prefer Supabase REST signed upload URLs. Fall back to S3 presigns when
    REST credentials are unavailable (e.g. local unit tests with stub env).
    """
    if content_type is None:
        content_type = content_type_for_path(path)

    key = _get_key(path)
    bucket = bucket_for_key(key)

    if _rest_enabled():
        try:
            return _rest_signed_upload_link(key, bucket), content_type
        except Exception as error:
            logger.warning("REST signed upload URL failed, falling back to S3: %s", error)

    return _s3_presigned_upload_link(key, content_type, bucket), content_type


def _rest_signed_upload_link(key: str, bucket: str) -> str:
    """Create a time-limited Supabase Storage signed upload URL."""
    url = (
        f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/upload/sign/"
        f"{bucket}/{key}"
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


def _s3_presigned_upload_link(key: str, content_type: str, bucket: str) -> str:
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
    }
    return s3.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=3600,
    )


def _rest_upload(key: str, data, content_type=None):
    bucket = bucket_for_key(key)
    url = (
        f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
        f"{bucket}/{key}"
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
    bucket = bucket_for_key(key)

    if _rest_enabled():
        try:
            url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
                f"{bucket}/{key}"
            )
            response = requests.delete(url, headers=_storage_headers(), timeout=30)
            if response.status_code in (200, 404):
                return
            response.raise_for_status()
            return
        except Exception as error:
            logger.warning("REST delete failed, falling back to S3: %s", error)

    response = s3.delete_object(Bucket=bucket, Key=key)

    if response["ResponseMetadata"]["HTTPStatusCode"] == 204:
        print(f"File '{file_url}' deleted successfully from bucket '{bucket}'.")
    else:
        print(f"Failed to delete file '{file_url}' from bucket '{bucket}'.")


def relocate_to_knowledge_folder(file) -> None:
    """Copy a public admin upload into the private knowledge folder.

    The admin UI uploads through POST /files, which stores
    /admins/<id>/files/<uuid>.<ext> in the public bucket. Licensed source
    text cannot stay there. When a knowledge source is saved, copy those
    bytes to knowledge/<owner>/<uuid>.<ext>, point the File row at that
    key, then delete the public object. Files already in knowledge/ are
    left as they are. Other uploads (video, images, podcasts) are not
    moved unless a knowledge source is attached to them.
    """
    key = _get_key(getattr(file, "url", None) or "")
    if not key or key.startswith(f"{KNOWLEDGE_FOLDER}/"):
        return

    owner = getattr(file, "created_by_id", None) or "shared"
    filename = key.rsplit("/", 1)[-1]
    dest_key = f"{KNOWLEDGE_FOLDER}/{owner}/{filename}"

    data = _download_bytes(key, bucket_for_key(key))
    if not data:
        raise KnowledgeFileMissing(
            "This file has no stored bytes yet. Finish the upload, then attach it again."
        )

    result = upload(data, dest_key, content_type=content_type_for_path(dest_key))
    if isinstance(result, str) and result.startswith("Upload error"):
        logger.error("Knowledge file copy failed for %s: %s", key, result)
        raise KnowledgeFileMissing(
            "The file could not be copied into the private knowledge folder."
        )

    old_url = file.url
    file.url = f"/{dest_key}"
    file.save(update_fields=["url", "updated_at"])

    try:
        delete(old_url)
    except Exception as error:
        logger.warning(
            "Knowledge file %s was copied to %s but the public object was not deleted: %s",
            old_url,
            dest_key,
            error,
        )


def download_text(file_url: str) -> str:
    """Read a platform upload from the same bucket the upload was written to."""
    key = _get_key(file_url or "")
    if not key:
        return ""
    raw = _download_bytes(key, bucket_for_key(key))
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Uploaded file %s is not utf-8 text", key)
        return ""


def _download_bytes(key: str, bucket: str) -> bytes:
    if _rest_enabled():
        try:
            url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
                f"{bucket}/{key}"
            )
            response = requests.get(url, headers=_storage_headers(), timeout=60)
            if response.status_code == 404:
                return b""
            response.raise_for_status()
            return response.content
        except Exception as error:
            logger.warning("REST download failed, falling back to S3: %s", error)

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404", "NotFound"):
            return b""
        raise


def exists(file_url):
    key = _get_key(file_url)
    bucket = bucket_for_key(key)

    # Short timeout: upload confirm should not block the API for long.
    timeout = 5

    if _rest_enabled():
        try:
            auth_url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/"
                f"{bucket}/{key}"
            )
            head = requests.head(auth_url, headers=_storage_headers(), timeout=timeout)
            if head.status_code == 200:
                return True
            if head.status_code in (400, 404):
                return False
            if bucket != Api.SUPABASE_STORAGE_BUCKET:
                return False
            # Some gateways reject HEAD; try public info endpoint.
            info_url = (
                f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/info/public/"
                f"{bucket}/{key}"
            )
            info = requests.get(info_url, headers=_storage_headers(), timeout=timeout)
            return info.status_code == 200
        except Exception as error:
            logger.warning("REST exists check failed, falling back to S3: %s", error)

    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False

def _get_key(path):
    if path.startswith("/"):
        path = path[1:]

    return path
