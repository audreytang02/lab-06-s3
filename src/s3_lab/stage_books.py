#!/usr/bin/env python3
"""
Download Project Gutenberg books and publish them in a public S3 bucket.

Usage:
    uv run python src/s3_lab/stage_books.py book_urls.txt index.html public-mst3k
"""

import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError


# Configure logging so we can see progress and errors.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# Create one authenticated S3 client for all functions to share.
s3 = boto3.client("s3", region_name="us-east-1")


def parse_args():
    """Read the book list path, index path, and bucket name from the command line."""
    if len(sys.argv) != 4:
        log.error(
            "Usage: python stage_books.py LIST_FILE INDEX_PATH BUCKET"
        )
        sys.exit(1)

    list_file = sys.argv[1]
    index_path = sys.argv[2]
    bucket = sys.argv[3]

    return list_file, index_path, bucket


def download_books(list_file, dest_dir):
    """Download books listed in list_file and return their local file paths."""
    downloaded_files = []

    try:
        os.makedirs(dest_dir, exist_ok=True)

        with open(list_file, "r", encoding="utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]

    except OSError as e:
        log.error("Could not read book list or create destination folder: %s", e)
        return downloaded_files

    for url in urls:
        # Use the final part of the URL as the filename.
        filename = url.split("?")[0].rstrip("/").split("/")[-1]

        if not filename:
            log.error("Could not determine filename from URL: %s", url)
            continue

        path = os.path.join(dest_dir, filename)

        if os.path.exists(path):
            log.info("Book already exists; skipping download: %s", path)
            downloaded_files.append(path)
            continue

        try:
            log.info("Downloading %s", url)
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            with open(path, "wb") as book_file:
                book_file.write(response.content)

            downloaded_files.append(path)
            log.info("Saved book to %s", path)

        except requests.RequestException as e:
            log.error("Error downloading %s: %s", url, e)

        except OSError as e:
            log.error("Error saving book from %s: %s", url, e)

        # Pause between requests to avoid overloading Project Gutenberg.
        time.sleep(1)

    log.info("Found %d usable book files.", len(downloaded_files))
    return downloaded_files


def create_bucket(bucket):
    """Create the S3 bucket if necessary and return whether it is available."""
    try:
        s3.head_bucket(Bucket=bucket)
        log.info("Bucket already exists and is accessible: %s", bucket)
        return True

    except ClientError as e:
        log.info("Bucket was not confirmed to exist; attempting creation.")

    try:
        # us-east-1 does not require a LocationConstraint.
        s3.create_bucket(Bucket=bucket)
        log.info("Created bucket: %s", bucket)
        return True

    except ClientError as e:
        log.error("Could not create bucket %s: %s", bucket, e)
        return False


def make_public(bucket):
    """Allow public read access to objects in the bucket."""
    try:
        # Disable the bucket-level settings that block public policies.
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info("Updated public access block settings for %s", bucket)

        # Allow anyone to read objects, but not upload or delete them.
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                }
            ],
        }

        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(policy),
        )
        log.info("Applied public read policy to %s", bucket)
        return True

    except ClientError as e:
        log.error("Could not make bucket %s public: %s", bucket, e)
        return False


def upload_files(bucket, file_paths):
    """Upload book files to the top level of the bucket and count successes."""
    uploaded_count = 0

    for path in file_paths:
        filename = os.path.basename(path)

        try:
            s3.upload_file(
                path,
                bucket,
                filename,
                ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
            )
            uploaded_count += 1
            log.info("Uploaded %s to bucket %s", filename, bucket)

        except (ClientError, OSError) as e:
            log.error("Could not upload %s: %s", path, e)

    log.info("Successfully uploaded %d book files.", uploaded_count)
    return uploaded_count


def upload_index(bucket, index_path):
    """Upload the index page as index.html and return whether it succeeded."""
    try:
        s3.upload_file(
            index_path,
            bucket,
            "index.html",
            ExtraArgs={"ContentType": "text/html"},
        )
        log.info("Uploaded index page to bucket %s", bucket)
        return True

    except (ClientError, OSError) as e:
        log.error("Could not upload index file %s: %s", index_path, e)
        return False


def main():
    """Run the book download, bucket setup, and upload workflow."""
    list_file, index_path, bucket = parse_args()

    # Download books first so we can stop if none are available.
    file_paths = download_books(list_file, "books")

    if not file_paths:
        log.error("No books were downloaded or found. Stopping.")
        sys.exit(1)

    if not create_bucket(bucket):
        log.error("Bucket creation or access failed. Stopping.")
        sys.exit(1)

    if not make_public(bucket):
        log.error("Could not configure public access. Stopping.")
        sys.exit(1)

    uploaded_count = upload_files(bucket, file_paths)

    if uploaded_count == 0:
        log.error("No book files were uploaded successfully.")
        sys.exit(1)

    if not upload_index(bucket, index_path):
        log.error("Index upload failed.")
        sys.exit(1)

    index_url = f"https://{bucket}.s3.amazonaws.com/index.html"
    log.info("Task completed successfully!")
    log.info("Public index URL: %s", index_url)


if __name__ == "__main__":
    main()
