"""
Planned vs Earned Value app configuration.
"""

from django.apps import AppConfig


class PlannedEarnedValueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "planned_earned_value"
    verbose_name = "Planned vs Earned Value"
