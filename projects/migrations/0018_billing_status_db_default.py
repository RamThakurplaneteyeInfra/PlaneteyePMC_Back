# Persistent DB default for billing_status so older app code that omits
# the column on INSERT does not hit NOT NULL IntegrityError.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0017_project_billing_completion_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE projects_project "
                "ALTER COLUMN billing_status SET DEFAULT 'Pending';"
            ),
            reverse_sql=(
                "ALTER TABLE projects_project "
                "ALTER COLUMN billing_status DROP DEFAULT;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE projects_project "
                "SET billing_status = 'Pending' "
                "WHERE billing_status IS NULL OR billing_status = '';"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
