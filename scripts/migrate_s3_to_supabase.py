#!/usr/bin/env python3
"""
One-off migration: copy every object from the old AWS S3 bucket into the new
Supabase Storage bucket (accessed via Supabase's S3-compatible API), key for
key, so existing images/files/chat-logs keep working after the app switches
over to Supabase Storage.

This script is standalone (no Django import needed) — it only talks to two
S3-compatible endpoints directly via boto3.

Usage:
    python scripts/migrate_s3_to_supabase.py [--prefix PREFIX] [--dry-run] [--delete-source]

Required environment variables:
    # Source (old AWS S3 bucket)
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_S3_BUCKET_NAME
    AWS_REGION                     (default: eu-west-1, matches the app's old default)

    # Destination (Supabase Storage, S3-compatible API)
    SUPABASE_STORAGE_S3_ENDPOINT   e.g. https://<project_ref>.storage.supabase.co/storage/v1/s3
    SUPABASE_STORAGE_ACCESS_KEY_ID
    SUPABASE_STORAGE_SECRET_ACCESS_KEY
    SUPABASE_STORAGE_REGION        (default: us-east-1)
    SUPABASE_STORAGE_BUCKET        Public bucket (images/files)
    SUPABASE_STORAGE_PRIVATE_BUCKET  Private bucket (chat logs). Defaults to
                                    SUPABASE_STORAGE_BUCKET if unset -- but see
                                    the note below about keeping PII private.

Key routing:
    Every key in the source bucket is copied to SUPABASE_STORAGE_BUCKET
    (the public bucket), EXCEPT keys matching "consumers/*/chat_log.txt",
    which contain consumer PII and are routed to SUPABASE_STORAGE_PRIVATE_BUCKET
    instead. Adjust `_destination_bucket()` below if your key layout differs.

This script only *copies*; it never deletes from the source bucket unless you
pass --delete-source (do this only after verifying the app works end-to-end
against Supabase Storage).
"""
import argparse
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"ERROR: required environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


def build_source_client():
    return boto3.client(
        "s3",
        aws_access_key_id=_require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_require_env("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def build_destination_client():
    return boto3.client(
        "s3",
        aws_access_key_id=_require_env("SUPABASE_STORAGE_ACCESS_KEY_ID"),
        aws_secret_access_key=_require_env("SUPABASE_STORAGE_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("SUPABASE_STORAGE_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        endpoint_url=_require_env("SUPABASE_STORAGE_S3_ENDPOINT"),
    )


def destination_bucket(key: str, public_bucket: str, private_bucket: str) -> str:
    """Chat logs (consumers/<id>/chat_log.txt) contain PII and must land in
    the private bucket; everything else (images/files) is public."""
    if key.endswith("/chat_log.txt") or key == "chat_log.txt":
        return private_bucket
    return public_bucket


def iter_source_keys(source_client, bucket: str, prefix: str):
    paginator = source_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", default="", help="Only migrate keys under this prefix")
    parser.add_argument("--dry-run", action="store_true", help="List what would be copied without copying")
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="After a successful copy, delete the object from the source (AWS) bucket. "
             "Only use this once you've verified the app works against Supabase Storage.",
    )
    args = parser.parse_args()

    source_bucket = _require_env("AWS_S3_BUCKET_NAME")
    public_bucket = _require_env("SUPABASE_STORAGE_BUCKET")
    private_bucket = os.environ.get("SUPABASE_STORAGE_PRIVATE_BUCKET", public_bucket)

    if private_bucket == public_bucket:
        print(
            "WARNING: SUPABASE_STORAGE_PRIVATE_BUCKET is not set (or equals the public "
            "bucket) -- chat logs will be copied into the same bucket as public images/"
            "files. Make sure that bucket is NOT public, or set a separate private bucket, "
            "before proceeding.",
            file=sys.stderr,
        )

    source = build_source_client()
    destination = None if args.dry_run else build_destination_client()

    copied = 0
    skipped = 0
    failed = 0
    total_bytes = 0

    for key, size in iter_source_keys(source, source_bucket, args.prefix):
        dest_bucket = destination_bucket(key, public_bucket, private_bucket)

        if args.dry_run:
            print(f"[dry-run] would copy s3://{source_bucket}/{key} -> {dest_bucket}/{key} ({size} bytes)")
            copied += 1
            total_bytes += size
            continue

        try:
            # Skip if already present with the same size (idempotent re-runs).
            try:
                head = destination.head_object(Bucket=dest_bucket, Key=key)
                if head["ContentLength"] == size:
                    print(f"SKIP  {key} (already present, same size)")
                    skipped += 1
                    continue
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
                    raise

            obj = source.get_object(Bucket=source_bucket, Key=key)
            body = obj["Body"].read()
            content_type = obj.get("ContentType")

            put_kwargs = {"Bucket": dest_bucket, "Key": key, "Body": body}
            if content_type:
                put_kwargs["ContentType"] = content_type

            destination.put_object(**put_kwargs)
            print(f"COPY  {key} -> {dest_bucket} ({size} bytes)")
            copied += 1
            total_bytes += size

            if args.delete_source:
                source.delete_object(Bucket=source_bucket, Key=key)
                print(f"      deleted source s3://{source_bucket}/{key}")

        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"FAIL  {key}: {exc!r}", file=sys.stderr)
            failed += 1

    print()
    print(f"Done. copied={copied} skipped={skipped} failed={failed} total_bytes={total_bytes}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
