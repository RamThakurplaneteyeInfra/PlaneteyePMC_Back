# Django app initialization + optional Celery app import.
# Importing celery here ensures `celery -A backend` workers discover the app.
# Tasks are eager by default — no broker/Redis required for normal API use.

from .celery import app as celery_app

__all__ = ("celery_app",)
