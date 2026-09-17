from django.apps import AppConfig


class MprConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mpr"
    verbose_name = "Monthly Progress Report"

    def ready(self):
        from . import signals  # noqa: F401

        try:
            from mpr.services.mpr_executor import get_mpr_executor

            get_mpr_executor()
        except Exception:
            pass
