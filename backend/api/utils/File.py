import logging
import base64, uuid, six, os
from django.core.files.base import ContentFile
import boto3
from botocore.exceptions import ClientError
from ..utils import Constants, Api, Exception as CustomException
from botocore.config import Config

# set boto lib debug to critical
logging.getLogger('boto').setLevel(logging.CRITICAL)

region = "eu-west-1"

s3 = boto3.client(
    's3',
    aws_access_key_id=Api.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=Api.AWS_SECRET_ACCESS_KEY,
    region_name=region,
    # todo remove addressing_style and endpoint url in future when S3 dns propagates?
    # https://github.com/boto/boto3/issues/2989#issuecomment-915011727
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}),
    endpoint_url=f'https://s3.{region}.amazonaws.com',
)

IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg"]


def upload(data, full_path, content_type=None, public=True):
    try:
        s3.put_object(Bucket=Api.AWS_S3_BUCKET_NAME, Key=_get_key(full_path), Body=data)
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


def get_upload_link(path):
    link = s3.generate_presigned_url(
        'put_object',
        Params={'Bucket': Api.AWS_S3_BUCKET_NAME, 'Key': _get_key(path)},
        ExpiresIn=3600
    )
    return link


def delete(file_url):
    if not file_url:
        return

    response = s3.delete_object(Bucket=Api.AWS_S3_BUCKET_NAME, Key=file_url)

    # Check response for success
    if response['ResponseMetadata']['HTTPStatusCode'] == 204:
        print(f"File '{file_url}' deleted successfully from bucket '{Api.AWS_S3_BUCKET_NAME}'.")
    else:
        print(f"Failed to delete file '{file_url}' from bucket '{Api.AWS_S3_BUCKET_NAME}'.")


def exists(file_url):
    try:
        s3.head_object(Bucket=Api.AWS_S3_BUCKET_NAME, Key=_get_key(file_url))
        return True
    except ClientError as e:
        return False


def _get_key(path):
    if path.startswith("/"):
        path = path[1:]

    return path