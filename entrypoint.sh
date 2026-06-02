#!/bin/bash
set -e

echo "Starting PMC Backend deployment..."
echo "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-backend.settings_prod}"

# Verify critical Python packages (fail fast with a clear message)
python -c "
import sys
missing = []
for pkg in ('cloudinary', 'django', 'channels', 'daphne', 'psycopg2'):
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)
if missing:
    print('ERROR: Missing Python packages:', ', '.join(missing))
    print('Run: pip install -r requirements.txt')
    sys.exit(1)
print('Python dependencies OK (cloudinary, django, channels, daphne, psycopg2)')
"

if [ -z "$SECRET_KEY" ]; then
  echo "ERROR: SECRET_KEY environment variable is not set."
  exit 1
fi

if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ]; then
  echo "ERROR: Set DATABASE_URL (recommended) or DB_HOST for production database."
  exit 1
fi

if [ -z "$CLOUDINARY_CLOUD_NAME" ] || [ -z "$CLOUDINARY_API_KEY" ] || [ -z "$CLOUDINARY_API_SECRET" ]; then
  echo "WARNING: Cloudinary env vars missing — site image uploads will return 503 until configured."
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
