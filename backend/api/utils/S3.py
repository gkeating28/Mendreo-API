import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from . import Api

BUCKET_NAME = Api.AWS_S3_BUCKET_NAME

region = "eu-west-1"

s3_client = boto3.client(
    's3',
    aws_access_key_id=Api.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=Api.AWS_SECRET_ACCESS_KEY,
    region_name=region,
    # todo remove addressing_style and endpoint url in future when S3 dns propagates?
    # https://github.com/boto/boto3/issues/2989#issuecomment-915011727
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}),
    endpoint_url=f'https://s3.{region}.amazonaws.com',
)


def upload_text(key: str, text: str):
    """Upload plain text to S3 (overwrites existing)."""
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain",
        ACL="private"  # ensure private access
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
    """Also append to a single full log file for quick retrieval."""
    new_block = "\n".join(lines)
    existing_data = download_text(key, return_empty_on_file_not_found=True)
    upload_text(key, existing_data + new_block)
    # get_file = download_text(key)
    # print("get_file", get_file)

