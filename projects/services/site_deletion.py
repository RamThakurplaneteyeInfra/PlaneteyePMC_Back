"""
Safe Site deletion for Init List / site management.

Site has no soft-delete flag (status is operational: not_started/active/completed).
Only hard-delete when no reverse FK dependencies exist.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Count

from projects.models import Site

logger = logging.getLogger("pmc.sites.deletion")


def collect_site_dependencies(site: Site) -> dict[str, int]:
    """
    Count reverse-FK references that would cascade or orphan if deleted.

    Only models with a real FK to ``projects.Site`` are checked (efficient
    Exists/Count). Modules that key by project name alone are not Site deps.
    """
    # Annotated reverse counts via related managers (single round-trip where possible).
    annotated = (
        Site.objects.filter(pk=site.pk)
        .annotate(
            tasks_count=Count("tasks", distinct=True),
            dprs_count=Count("dprs", distinct=True),
        )
        .values("tasks_count", "dprs_count")
        .first()
    )
    if not annotated:
        return {}

    deps: dict[str, int] = {}
    # Friendly keys aligned with product language / API contract.
    if annotated["tasks_count"]:
        deps["tasks"] = int(annotated["tasks_count"])
    if annotated["dprs_count"]:
        deps["dpr"] = int(annotated["dprs_count"])
    return deps


def invalidate_site_related_caches() -> None:
    from core.cache_keys import invalidate_list_cache
    from core.cache_tags import invalidate_tags

    # Version-bump overview/dropdown/projects; init-list prefix for future caching.
    invalidate_tags("overview", "dropdown", "projects", "sites")
    invalidate_list_cache("projects_init_list")


def log_site_deletion(*, actor, site: Site, request=None) -> None:
    """Reuse user-management audit trail for site delete events."""
    from accounts.models import UserManagementAuditLog
    from accounts.user_management_services import log_user_management_action

    ip = ""
    if request is not None:
        ip = (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR", "")
            or ""
        )
    detail = (
        f"Deleted site id={site.pk} name={site.name!r} "
        f"project_id={site.project_id} project={site.project.name!r}."
    )
    if ip:
        detail = f"{detail} ip={ip}"

    log_user_management_action(
        performed_by=actor,
        target_user=actor,
        action=UserManagementAuditLog.ACTION_DELETED,
        detail=detail,
        projects=[site.project],
    )


class SiteDeleteBlocked(Exception):
    def __init__(self, dependencies: dict[str, int]):
        self.dependencies = dependencies
        super().__init__("Site has dependencies")


@transaction.atomic
def delete_site_safe(*, site: Site, actor, request=None) -> dict[str, Any]:
    """
    Hard-delete ``site`` when dependency-free.

    Raises ``SiteDeleteBlocked`` when reverse FKs exist.
    """
    site = (
        Site.objects.select_related("project")
        .only(
            "id",
            "name",
            "location",
            "status",
            "project_id",
            "project__id",
            "project__name",
        )
        .filter(pk=site.pk)
        .first()
    )
    if site is None:
        raise Site.DoesNotExist("Site not found")

    deps = collect_site_dependencies(site)
    if deps:
        raise SiteDeleteBlocked(deps)

    # Snapshot for audit before delete.
    log_site_deletion(actor=actor, site=site, request=request)
    site_id = site.pk
    site.delete()
    invalidate_site_related_caches()
    logger.info(
        "site_deleted site_id=%s actor=%s",
        site_id,
        getattr(actor, "username", None),
    )
    return {"success": True, "message": "Site deleted successfully."}
