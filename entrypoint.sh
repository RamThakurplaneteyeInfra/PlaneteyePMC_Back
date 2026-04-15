#!/bin/bash
set -e

echo "Starting PMC Backend deployment..."

# 🔥 STEP 1: Migrations handle cleanup, skipping manual cleanup

# 🔥 STEP 2: Run migrations (NOW SAFE)
echo "Running migrations..."
python manage.py migrate --noinput

# Step 3: Collect static
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Step 4: Superuser already created, skipping

# Step 5: Start server
echo "Starting Daphne..."
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port ${PORT:-8000} \
    --proxy-headers