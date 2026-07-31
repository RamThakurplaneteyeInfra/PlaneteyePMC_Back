"""Celery tasks for cache pre-warming and async revalidation."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("pmc.cache.tasks")


@shared_task(name="core.prewarm_project_caches")
def prewarm_project_caches() -> dict:
    """
    Rebuild frequently accessed caches after deploy / Redis restart.

    Safe to run eagerly (CELERY_TASK_ALWAYS_EAGER=true) or on a worker.
    """
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    from accounts.rbac import is_admin_user
    from projects.views import ProjectViewSet

    User = get_user_model()
    factory = RequestFactory()
    warmed = {"overview": 0, "dropdown": 0, "errors": 0}

    admin = (
        User.objects.filter(is_superuser=True, is_active=True).first()
        or next(
            (u for u in User.objects.filter(is_active=True)[:50] if is_admin_user(u)),
            None,
        )
    )
    if admin is None:
        logger.warning("prewarm skipped: no admin user")
        return warmed

    try:
        request = factory.get("/api/projects/overview/")
        request.user = admin
        # Hit the ViewSet path so the cached key matches live API responses.
        view = ProjectViewSet.as_view({"get": "overview"})
        response = view(request)
        if getattr(response, "status_code", 500) < 400:
            warmed["overview"] = 1
    except Exception as exc:
        warmed["errors"] += 1
        logger.warning("prewarm overview failed: %s", exc)

    try:
        request = factory.get("/api/projects/dropdown/?status=active")
        request.user = admin
        view = ProjectViewSet.as_view({"get": "dropdown"})
        response = view(request)
        if getattr(response, "status_code", 500) < 400:
            warmed["dropdown"] = 1
    except Exception as exc:
        warmed["errors"] += 1
        logger.warning("prewarm dropdown failed: %s", exc)

    logger.info("cache_prewarm complete %s", warmed)
    return warmed


@shared_task(name="core.revalidate_cache_key")
def revalidate_cache_key(builder_name: str, key: str, soft_ttl: int, hard_ttl: int) -> bool:
    """
    Placeholder async revalidator.

    Expensive builders that need request context should rebuild synchronously
    under lock; this task is for simple named builders registered below.
    """
    from core.cache_swr import swr_set

    builders = {}
    builder = builders.get(builder_name)
    if builder is None:
        logger.debug("no builder registered for %s", builder_name)
        return False
    try:
        payload = builder()
        swr_set(key, payload, soft_ttl=soft_ttl, hard_ttl=hard_ttl)
        return True
    except Exception as exc:
        logger.warning("revalidate failed builder=%s err=%s", builder_name, exc)
        return False
