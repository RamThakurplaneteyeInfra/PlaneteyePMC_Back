# Primary Site Engineer FK (one per project)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0011_projectlogentry_bottleneck_dashboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="site_engineer",
            field=models.ForeignKey(
                blank=True,
                help_text="Primary Site Engineer for this project (one per project)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="primary_site_engineer_projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
