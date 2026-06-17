#!/bin/bash
set -e

echo "Starting PMC Backend deployment..."
echo "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings_prod}"

# Verify critical Python packages (fail fast with a clear message)
python -c "
import sys
missing = []
for pkg in ('boto3', 'cloudinary', 'django', 'channels', 'daphne', 'psycopg2'):
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)
if missing:
    print('ERROR: Missing Python packages:', ', '.join(missing))
    print('Run: pip install -r requirements.txt')
    sys.exit(1)
print('Python dependencies OK (boto3, cloudinary, django, channels, daphne, psycopg2)')
"

if [ -z "$SECRET_KEY" ]; then
  echo "ERROR: SECRET_KEY environment variable is not set."
  exit 1
fi

if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ]; then
  echo "ERROR: Set DATABASE_URL (recommended) or DB_HOST for production database."
  exit 1
fi

s3_ready=0
cloud_ready=0
if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ] && [ -n "$AWS_STORAGE_BUCKET_NAME" ]; then
  s3_ready=1
fi
if [ -n "$CLOUDINARY_CLOUD_NAME" ] && [ -n "$CLOUDINARY_API_KEY" ] && [ -n "$CLOUDINARY_API_SECRET" ]; then
  cloud_ready=1
fi
if [ "$s3_ready" -eq 0 ] && [ "$cloud_ready" -eq 0 ]; then
  echo "WARNING: Neither AWS S3 nor Cloudinary is configured — site image uploads will return 503."
elif [ "$s3_ready" -eq 0 ]; then
  echo "WARNING: AWS S3 not configured — site images will use Cloudinary only."
elif [ "$cloud_ready" -eq 0 ]; then
  echo "WARNING: Cloudinary not configured — S3 is primary with no fallback."
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Daphne (Web Server) on port ${PORT:-8000}..."
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers
