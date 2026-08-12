"""
Orchestrate multi-file drawing uploads with S3 cleanup on failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.db import transaction

from core.business_audit import write_business_audit
from core.models import BusinessAuditLog
from mpr.services.cache import invalidate_mpr_cache
from services.s3_drawing_files import (
    delete_drawing_files_batch,
    upload_drawing_file,
    validate_upload_file,
)

from ..models.drawing_file import DrawingFile
from ..models.drawing_register import DrawingRegisterItem

logger = logging.getLogger(__name__)


def collect_drawing_files(request) -> list:
    """Collect uploaded files from multipart field ``drawings`` (repeatable)."""
    if not getattr(request, "FILES", None):
        return []

    collected: list = []
    seen: set[int] = set()

    def _add(file_list):
        for f in file_list:
            fid = id(f)
            if fid not in seen:
                seen.add(fid)
                collected.append(f)

    for key in ("drawings", "drawings[]"):
        _add(request.FILES.getlist(key))

    if not collected:
        for key in sorted(request.FILES.keys()):
            if key == "drawings" or key.startswith("drawings"):
                _add(request.FILES.getlist(key))

    return collected


def prepare_register_payload(data) -> dict:
    """
    Normalize multipart form data for DrawingRegisterItemSerializer.

    - workflow_events may arrive as a JSON string
    - empty strings for optional dates → None
    """
    if hasattr(data, "copy"):
        payload = data.copy()
    else:
        payload = dict(data)

    if isinstance(payload, QueryDict):
        payload = {key: payload.get(key) for key in payload.keys()}

    for field in (
        "submitted_date",
        "consultant_comments_date",
        "resubmitted_date",
        "approved_date",
    ):
        if field in payload:
            val = payload.get(field)
            if val in ("", "null", "None", None):
                payload[field] = None

    wf = payload.get("workflow_events")
    if isinstance(wf, str) and wf.strip():
        try:
            payload["workflow_events"] = json.loads(wf)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                {"workflow_events": f"Invalid JSON: {exc.msg}"}
            ) from exc

    return payload


def validate_all_uploads(uploaded_files: list) -> None:
    """Validate every file before any S3/DB work."""
    errors = []
    for f in uploaded_files:
        try:
            validate_upload_file(f)
        except ValidationError as exc:
            name = getattr(f, "name", "file")
            errors.append(f"{name}: {exc.messages[0] if exc.messages else exc}")
    if errors:
        raise ValidationError({"drawings": errors})


def persist_drawing_files(
    *,
    register_item: DrawingRegisterItem,
    uploaded_files: list,
    actor,
    revision: int | None = None,
) -> list[DrawingFile]:
    """
    Upload files to S3 (outside DB transaction) then persist metadata.

    On any failure, cleans up S3 keys and DrawingFile rows from this batch.
    """
    if not uploaded_files:
        return []

    rev = revision if revision is not None else register_item.revision
    project_id = register_item.project_id
    register_id = register_item.id

    uploaded_keys: list[str] = []
    created: list[DrawingFile] = []

    try:
        for uploaded_file in uploaded_files:
            result = upload_drawing_file(
                uploaded_file=uploaded_file,
                project_id=project_id,
                register_id=register_id,
                revision=rev,
            )
            uploaded_keys.append(result["s3_key"])
            with transaction.atomic():
                row = DrawingFile.objects.create(
                    drawing_register=register_item,
                    revision=rev,
                    original_filename=result["original_filename"],
                    s3_key=result["s3_key"],
                    file_url=result["file_url"],
                    file_size=result["file_size"],
                    content_type=result["content_type"],
                    file_extension=result["file_extension"],
                    uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
                    is_active=True,
                )
            created.append(row)
            write_business_audit(
                entity_type=BusinessAuditLog.ENTITY_DRAWING,
                action=BusinessAuditLog.ACTION_UPLOADED,
                actor=actor,
                entity_id=row.id,
                project=register_item.project,
                detail=(
                    f"drawing_file uploaded register_id={register_id} "
                    f"revision={rev} filename={result['original_filename']!r}"
                ),
            )
    except Exception:
        if created:
            DrawingFile.objects.filter(id__in=[r.id for r in created]).delete()
        delete_drawing_files_batch(uploaded_keys)
        raise

    invalidate_mpr_cache()
    return created


def soft_delete_drawing_file(*, drawing_file: DrawingFile, actor) -> None:
    """Soft-delete metadata and remove S3 object."""
    from services.s3_drawing_files import delete_drawing_file

    s3_key = drawing_file.s3_key
    register = drawing_file.drawing_register
    file_id = drawing_file.id
    revision = drawing_file.revision

    drawing_file.is_active = False
    drawing_file.save(update_fields=["is_active", "updated_at"])
    delete_drawing_file(s3_key)

    write_business_audit(
        entity_type=BusinessAuditLog.ENTITY_DRAWING,
        action=BusinessAuditLog.ACTION_DELETED,
        actor=actor,
        entity_id=file_id,
        project=register.project if register else None,
        detail=(
            f"drawing_file deleted register_id={register.id if register else ''} "
            f"revision={revision} s3_key={s3_key!r}"
        ),
    )
    invalidate_mpr_cache()


def delete_register_s3_files(register_item: DrawingRegisterItem) -> None:
    """Remove all S3 objects when a register row is deleted."""
    keys = list(
        DrawingFile.objects.filter(drawing_register=register_item).values_list(
            "s3_key", flat=True
        )
    )
    delete_drawing_files_batch(keys)
