"""
Celery application for background jobs (DPR email, cache prewarm, etc.).

Broker defaults to REDIS_URL when set. For async email delivery in production:
  CELERY_TASK_ALWAYS_EAGER=false
  celery -A backend worker -l info
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
