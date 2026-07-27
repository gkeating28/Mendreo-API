import logging
import base64, uuid, six, os
from django.core.files.base import ContentFile
import boto3
from botocore.exceptions import ClientError
from ..utils import Constants, Api, Exception as CustomException
from botocore.config import Config

# set boto lib debug to critical
logging.getLogger('boto').setLevel(logging.CRITICAL)

# Object storage lives on Supabase Storage, reached via its S3-compatible API
# (see api/utils/Api.py for env var docs). Supabase's S3 gateway requires
# path-style addressing ("forcePathStyle") rather than the virtual-hosted
# style AWS uses by default.
s3 = boto3.client(
    's3',
    aws_access_key_id=Api.SUPABASE_STORAGE_ACCESS_KEY_ID,
    aws_secret_access_key=Api.SUPABASE_STORAGE_SECRET_ACCESS_KEY,
    region_name=Api.SUPABASE_STORAGE_REGION,
    config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    endpoint_url=Api.SUPABASE_STORAGE_S3_ENDPOINT,
)

IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg"]

# Browser File.type values the Content Editor will send on PUT. These MUST be
# included in the presigned signature or Supabase returns 403.
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


def upload(data, full_path, content_type=None, public=True):
    try:
        params = {
            "Bucket": Api.SUPABASE_STORAGE_BUCKET,
            "Key": _get_key(full_path),
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
    return ext[len(ext)-1].lower()


def get_image_extension(file):

    allowed_extensions = Constants.IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS

    ext = file.name.split(".")

    if ext[len(ext)-1].lower() in allowed_extensions:
        return ext[len(ext)-1].lower()
    else:
        return "jpg"


def get_upload_link(path, content_type=None):
    """Presign a PUT. content_type is signed so browser uploads that send
    File.type / Content-Type succeed against Supabase's S3 gateway.

    Returns (url, content_type).
    """
    if content_type is None:
        content_type = content_type_for_path(path)

    params = {
        "Bucket": Api.SUPABASE_STORAGE_BUCKET,
        "Key": _get_key(path),
        "ContentType": content_type,
    }
    link = s3.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=3600,
    )
    return link, content_type


def delete(file_url):
    if not file_url:
        return

    response = s3.delete_object(Bucket=Api.SUPABASE_STORAGE_BUCKET, Key=_get_key(file_url))

    # Check response for success
    if response['ResponseMetadata']['HTTPStatusCode'] == 204:
        print(f"File '{file_url}' deleted successfully from bucket '{Api.SUPABASE_STORAGE_BUCKET}'.")
    else:
        print(f"Failed to delete file '{file_url}' from bucket '{Api.SUPABASE_STORAGE_BUCKET}'.")


def exists(file_url):
    try:
        s3.head_object(Bucket=Api.SUPABASE_STORAGE_BUCKET, Key=_get_key(file_url))
        return True
    except ClientError as e:
        return False


def _get_key(path):
    if path.startswith("/"):
        path = path[1:]

    return path
