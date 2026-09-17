"""
Helpers for writing BusinessAuditLog entries without affecting API responses.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("pmc.audit")


def write_business_audit(
    *,
    entity_type: str,
    action: str,
    actor=None,
    entity_id: Any = "",
    project=None,
    project_name: str = "",
    detail: str = "",
) -> None:
    """
    Persist a business audit row. Never raises to callers — audit must not
    break the primary mutation path.
    """
    try:
        from core.models import BusinessAuditLog

        name = project_name or ""
        if project is not None and not name:
            name = getattr(project, "name", "") or ""

        BusinessAuditLog.objects.create(
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            project=project if getattr(project, "pk", None) else None,
            project_name=name[:255],
            action=action,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            detail=(detail or "")[:4000],
        )
    except Exception:
        logger.exception(
            "business_audit_failed entity_type=%s action=%s entity_id=%s",
            entity_type,
            action,
            entity_id,
        )
