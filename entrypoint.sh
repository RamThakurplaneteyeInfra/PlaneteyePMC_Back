#!/bin/bash
set -e

echo "Starting PMC Backend deployment..."

# 🔥 STEP 1: Try cleanup safely (ignore errors if table doesn't exist)
echo "Cleaning duplicate DPR data..."

python manage.py shell << EOF || true
from django.db.models import Count
from dpr.models import DPR

try:
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

except Exception as e:
    print("Cleanup skipped:", e)
EOF

# 🔥 STEP 2: Run migrations (NOW SAFE)
echo "Running migrations..."
python manage.py migrate --noinput

# Step 3: Collect static
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Step 4: Create superuser
echo "Creating superuser..."
python manage.py createsuperuser --noinput || true

# Step 5: Start server
echo "Starting Daphne..."
exec daphne backend.asgi:application \
    --bind 0.0.0.0 \
    --port ${PORT:-8000} \
    --proxy-headers