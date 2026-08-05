#!/bin/bash
set -e

# Shared entrypoint for Railway Backend (Daphne) and Celery Worker services.
# Same image / repo; process selected by SERVICE_ROLE or custom start-command args.
#
# Backend (default):  migrate → collectstatic → daphne
# Worker:             SERVICE_ROLE=worker  OR  Railway Start Command → celery …

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-backend.settings_prod}"

echo "Starting PMC Backend container..."
echo "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"
echo "SERVICE_ROLE=${SERVICE_ROLE:-web}"

python -c "
import sys
missing = []
for pkg in ('boto3', 'cloudinary', 'django', 'channels', 'daphne', 'psycopg2', 'celery', 'redis'):
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)
if missing:
    print('ERROR: Missing Python packages:', ', '.join(missing))
    print('Run: pip install -r requirements.txt')
    sys.exit(1)
print('Python dependencies OK')
"

validate_core_env() {
  if [ -z "$SECRET_KEY" ]; then
    echo "ERROR: SECRET_KEY environment variable is not set."
    exit 1
  fi
  if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ]; then
    echo "ERROR: Set DATABASE_URL (recommended) or DB_HOST for production database."
    exit 1
  fi
}

validate_worker_env() {
  validate_core_env
  if [ -z "$REDIS_URL" ] && [ -z "$CELERY_BROKER_URL" ]; then
    echo "ERROR: REDIS_URL or CELERY_BROKER_URL is required for the Celery worker."
    exit 1
  fi
  eager="$(echo "${CELERY_TASK_ALWAYS_EAGER:-false}" | tr '[:upper:]' '[:lower:]')"
  if [ "$eager" = "true" ]; then
    echo "WARNING: CELERY_TASK_ALWAYS_EAGER=true — worker will still run but web may execute tasks inline."
  fi
}

# Railway Custom Start Command is passed as arguments to this ENTRYPOINT.
# Example: celery -A backend worker -l info
if [ "$#" -gt 0 ]; then
  validate_worker_env
  echo "Executing custom start command: $*"
  exec "$@"
fi

# Dedicated worker service (same Dockerfile; set SERVICE_ROLE=worker on Railway)
if [ "${SERVICE_ROLE:-web}" = "worker" ]; then
  validate_worker_env
  concurrency="${CELERY_CONCURRENCY:-2}"
  echo "Starting Celery worker (concurrency=${concurrency})..."
  echo "Broker: CELERY_BROKER_URL or REDIS_URL"
  exec celery -A backend worker -l info --concurrency="${concurrency}"
fi

# -------------------- Web service (Daphne) --------------------
validate_core_env

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
echo "(DPR emails use in-process ThreadPoolExecutor — no Celery worker required)"
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers
