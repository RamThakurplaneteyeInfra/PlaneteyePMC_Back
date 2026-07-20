"""
Celery application for optional background jobs.

Default configuration runs tasks eagerly in-process (no broker required).
Existing request paths do NOT depend on Celery. Enable a real broker later
via CELERY_BROKER_URL / CELERY_TASK_ALWAYS_EAGER=false when ready.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

app = Celery("backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(name="backend.ping")
def ping() -> str:
    """Example health-check task (not used by production request flows)."""
    return "pong"
