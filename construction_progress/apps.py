"""
Construction Progress app configuration.
"""

from django.apps import AppConfig


class ConstructionProgressConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "construction_progress"
    verbose_name = "Monthly Construction Progress"
