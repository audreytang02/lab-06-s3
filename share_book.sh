
#!/bin/bash
set -euo pipefail

# Check that all three required arguments were provided.
if [[ "$#" -ne 3 ]]; then
    echo "Usage: $0 BOOK_URL BUCKET EXPIRATION_SECONDS" >&2
    exit 1
fi

# Store the book URL, bucket name, and expiration time.
BOOK_URL="$1"
BUCKET="$2"
EXPIRES="$3"

# Make sure the expiration is a positive integer.
if ! [[ "$EXPIRES" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: expiration must be a positive integer." >&2
    exit 1
fi

# Extract the filename from the URL.
FILENAME="${BOOK_URL##*/}"

if [[ -z "$FILENAME" ]]; then
    echo "Error: could not determine filename from URL." >&2
    exit 1
fi

# Create the books folder and download the book, preserving its filename.
mkdir -p books
echo "Downloading $FILENAME..."
curl --fail --location --silent --show-error --retry 2 \
    "$BOOK_URL" --output "books/$FILENAME"

# Create the bucket only if it does not already exist and remain accessible.
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket already exists and is accessible: $BUCKET"
else
    echo "Creating private bucket: $BUCKET"
    aws s3 mb "s3://$BUCKET" --region us-east-1
fi

# Upload the book as plain text without making it public.
aws s3 cp "books/$FILENAME" "s3://$BUCKET/$FILENAME" \
    --content-type "text/plain; charset=utf-8"

# Generate and print a presigned URL with the requested expiration.
PRESIGNED_URL="$(aws s3 presign "s3://$BUCKET/$FILENAME" \
    --expires-in "$EXPIRES" --region us-east-1)"

echo "Presigned URL (expires after $EXPIRES seconds):"
echo "$PRESIGNED_URL"
