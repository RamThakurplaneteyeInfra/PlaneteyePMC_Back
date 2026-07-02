"""Shared contractor resolution for PMC modules."""

from __future__ import annotations

from rest_framework import serializers

from projects.models import Project

from .models import Contractor


def contractor_payload(contractor: Contractor | None) -> dict | None:
    if contractor is None:
        return None
    return {
        "id": contractor.id,
        "contractor_name": contractor.contractor_name,
    }


def get_active_contractor_for_project(
    project: Project,
    contractor_id: int | None,
    *,
    allow_inactive: bool = False,
) -> Contractor:
    if not contractor_id:
        raise serializers.ValidationError(
            {"contractor_id": "contractor_id is required for CONTRACTOR records."}
        )

    try:
        contractor = Contractor.objects.get(pk=contractor_id, project=project)
    except Contractor.DoesNotExist:
        raise serializers.ValidationError(
            {"contractor_id": f"No contractor with id {contractor_id} found for this project."}
        )

    if not allow_inactive and contractor.status != Contractor.Status.ACTIVE:
        raise serializers.ValidationError(
            {"contractor_id": f"Contractor '{contractor.contractor_name}' is not active."}
        )

    return contractor


def resolve_contractor_for_write(
    project: Project,
    *,
    contractor_id: int | None = None,
    contractor_name: str | None = None,
    require_active: bool = True,
) -> Contractor | None:
    """
    Resolve contractor from id (preferred) or legacy contractor_name.

    Returns None when neither is provided (valid for SCL rows).
    """
    if contractor_id:
        return get_active_contractor_for_project(
            project,
            contractor_id,
            allow_inactive=not require_active,
        )

    name = (contractor_name or "").strip()
    if not name:
        raise serializers.ValidationError(
            {"contractor_id": "contractor_id is required for CONTRACTOR records."}
        )

    contractor = Contractor.objects.filter(
        project=project,
        contractor_name__iexact=name,
    ).first()

    if contractor is None:
        raise serializers.ValidationError(
            {
                "contractor_id": (
                    f"No contractor named '{name}' found for this project. "
                    "Create the contractor in Contractor Management first."
                )
            }
        )

    if require_active and contractor.status != Contractor.Status.ACTIVE:
        raise serializers.ValidationError(
            {"contractor_id": f"Contractor '{contractor.contractor_name}' is not active."}
        )

    return contractor


def sync_contractor_name(instance, contractor: Contractor | None) -> None:
    """Keep denormalized contractor_name in sync with Contractor FK."""
    if contractor is not None:
        instance.contractor = contractor
        instance.contractor_name = contractor.contractor_name
    else:
        instance.contractor = None
        instance.contractor_name = None
