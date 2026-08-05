from django.apps import AppConfig


class DprConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dpr"
    verbose_name = "Daily Progress Reports"

    def ready(self):
        # Ensure singleton EMAIL_EXECUTOR + atexit shutdown are registered at startup.
        try:
            from dpr.email_executor import get_email_executor

            get_email_executor()
        except Exception:
            pass
