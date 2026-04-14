#!/bin/bash

# Exit on error
set -e

echo "Starting PMC Backend deployment..."

# Run migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Create superuser if it doesn't exist
echo "Checking for superuser..."
python manage.py shell << EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()

# Get superuser credentials from environment variables
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin123')

# Check if superuser exists
if not User.objects.filter(username=username).exists():
    print(f"Creating superuser: {username}")
    User.objects.create_superuser(username=username, email=email, password=password)
    print("Superuser created successfully!")
else:
    print(f"Superuser '{username}' already exists")
EOF

echo "Starting Daphne ASGI server for WebSocket support..."
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port 8000 \
    --access-log \
    --proxy-headers
