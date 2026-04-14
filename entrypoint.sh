#!/bin/bash
set -e

echo "Starting PMC Backend deployment..."

# Step 1: Run migrations FIRST
echo "Running migrations..."
python manage.py migrate --noinput

# Step 2: Clean duplicates AFTER migration
echo "Cleaning duplicate DPR data..."

python manage.py shell << EOF
from django.db.models import Count
from dpr.models import DPR

duplicates = (
    DPR.objects
    .values('project_name', 'report_date')
    .annotate(count=Count('id'))
    .filter(count__gt=1)
)

for item in duplicates:
    qs = DPR.objects.filter(
        project_name=item['project_name'],
        report_date=item['report_date']
    )
    qs.exclude(id=qs.first().id).delete()

print("Duplicate cleanup done")
EOF

# Step 3: Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Step 4: Create superuser safely
echo "Creating superuser..."
python manage.py createsuperuser --noinput || true

# Step 5: Start server
echo "Starting Daphne..."
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port ${PORT:-8000} \
    --proxy-headers