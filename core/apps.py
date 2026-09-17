from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "PMC Core"

    def ready(self):
        # Optional cold-start prewarm (off by default — set CACHE_PREWARM_ON_STARTUP=true).
        import os
        import sys
        import threading

        if os.environ.get("CACHE_PREWARM_ON_STARTUP", "").lower() != "true":
            return
        if "test" in sys.argv or os.environ.get("PYTEST_CURRENT_TEST"):
            return

        def _run():
            try:
                from core.tasks import prewarm_project_caches

                prewarm_project_caches()
            except Exception:
                pass

        threading.Timer(3.0, _run).start()
