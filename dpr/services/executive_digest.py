"""
Single source of truth for sending the DPR executive digest.

Callers:
  - management command ``send_dpr_executive_digest``
  - Celery task ``dpr.send_executive_digest``
  - internal API ``POST /api/internal/dpr/executive-digest/``
  - ``services.notifications.notify_dpr_executive_digest`` (compat wrapper)
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.business_audit import write_business_audit
from core.models import BusinessAuditLog
from dpr.services.digest import (
    build_executive_digest,
    resolve_digest_recipients,
)

logger = logging.getLogger("pmc.dpr.digest")

_IST = ZoneInfo("Asia/Kolkata")
_LOG = "[DPR Digest]"

# Idempotency TTLs (seconds)
_RUNNING_TTL = 15 * 60  # stale lock recovery
_COMPLETED_TTL = 36 * 60 * 60  # cover the business day + retries
_FAILED_TTL = 60 * 60  # allow retry after failure


def business_localdate() -> date:
    """Business calendar date for digest idempotency (Asia/Kolkata)."""
    return timezone.now().astimezone(_IST).date()


def _idempotency_key(report_date: date) -> str:
    return f"dpr:executive-digest:{report_date.isoformat()}"


def _cache_get_status(key: str) -> str | None:
    value = cache.get(key)
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    return str(value)


def _acquire_idempotency(report_date: date, *, force: bool = False) -> dict[str, Any]:
    """
    Returns dict with keys:
      ok: bool
      status: running | already_processed | acquired | force
    """
    key = _idempotency_key(report_date)
    if force:
        cache.set(key, "running", timeout=_RUNNING_TTL)
        return {"ok": True, "status": "force", "key": key}

    current = _cache_get_status(key)
    if current == "completed":
        return {"ok": False, "status": "already_processed", "key": key}
    if current == "running":
        return {"ok": False, "status": "running", "key": key}
    if current == "failed":
        # Allow retry after a previous failure.
        cache.delete(key)

    acquired = cache.add(key, "running", timeout=_RUNNING_TTL)
    if acquired:
        return {"ok": True, "status": "acquired", "key": key}

    # Race: another worker won between get and add.
    current = _cache_get_status(key)
    if current == "completed":
        return {"ok": False, "status": "already_processed", "key": key}
    return {"ok": False, "status": "running", "key": key}


def _mark_completed(key: str) -> None:
    cache.set(key, "completed", timeout=_COMPLETED_TTL)


def _mark_failed(key: str) -> None:
    cache.set(key, "failed", timeout=_FAILED_TTL)


def send_dpr_executive_digest(
    *,
    report_date: date | None = None,
    dry_run: bool = False,
    force: bool = False,
    source: str = "unknown",
    use_idempotency: bool = True,
) -> dict[str, Any]:
    """
    Build and queue/send the PMC Head + Head Office DPR executive digest.

    Returns a structured result (never raises for normal control flow).
    Status values include: queued, sent, dry_run, already_processed, running,
    skipped_no_recipients, disabled, email_disabled, failed.
    """
    started = time.monotonic()
    target_date = report_date or business_localdate()
    date_str = target_date.isoformat()

    logger.info(
        "%s Trigger received source=%s date=%s dry_run=%s force=%s",
        _LOG,
        source,
        date_str,
        dry_run,
        force,
    )

    if not getattr(settings, "DPR_DIGEST_ENABLED", True):
        logger.info("%s Disabled (DPR_DIGEST_ENABLED=false) date=%s", _LOG, date_str)
        return {
            "status": "disabled",
            "date": date_str,
            "report_date": date_str,
            "recipient_count": 0,
        }

    if not getattr(settings, "DPR_EMAIL_ENABLED", True) and not dry_run:
        logger.info("%s Skipped (DPR_EMAIL_ENABLED=false) date=%s", _LOG, date_str)
        return {
            "status": "email_disabled",
            "date": date_str,
            "report_date": date_str,
            "recipient_count": 0,
        }

    lock_key: str | None = None
    if use_idempotency and not dry_run:
        lock = _acquire_idempotency(target_date, force=force)
        lock_key = lock["key"]
        if not lock["ok"]:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "%s Idempotency blocked status=%s date=%s duration_ms=%s",
                _LOG,
                lock["status"],
                date_str,
                duration_ms,
            )
            return {
                "status": lock["status"],
                "date": date_str,
                "report_date": date_str,
                "recipient_count": 0,
                "duration_ms": duration_ms,
            }
        logger.info("%s Idempotency acquired date=%s", _LOG, date_str)

    try:
        logger.info("%s Building digest date=%s", _LOG, date_str)
        digest = build_executive_digest(report_date=target_date)
        recipients = resolve_digest_recipients()
        recipient_ids = [u.id for u in recipients]
        recipient_count = len(recipient_ids)

        summary: dict[str, Any] = {
            "status": "ready",
            "date": date_str,
            "report_date": date_str,
            "recipient_count": recipient_count,
            "filled": digest.counts.total_filled,
            "pending": digest.counts.pending_total,
            "missing": digest.counts.projects_missing,
            "active_projects": digest.counts.projects_active,
            "source": source,
        }

        if dry_run:
            summary["status"] = "dry_run"
            # Intentionally omit email addresses from returned payload.
            duration_ms = int((time.monotonic() - started) * 1000)
            summary["duration_ms"] = duration_ms
            logger.info(
                "%s Dry-run complete date=%s recipients=%s duration_ms=%s",
                _LOG,
                date_str,
                recipient_count,
                duration_ms,
            )
            return summary

        if not recipient_ids:
            summary["status"] = "skipped_no_recipients"
            if lock_key:
                _mark_failed(lock_key)
            write_business_audit(
                entity_type=BusinessAuditLog.ENTITY_DPR,
                action=BusinessAuditLog.ACTION_FAILED,
                entity_id=f"executive-digest:{date_str}",
                detail=f"DPR executive digest skipped — no recipients. source={source}",
            )
            logger.warning("%s No recipients date=%s", _LOG, date_str)
            return summary

        from dpr.tasks import send_dpr_executive_digest_email, submit_email_job

        if getattr(settings, "DPR_EMAIL_INLINE", False):
            result = send_dpr_executive_digest_email(
                report_date=date_str,
                recipient_ids=recipient_ids,
            )
            status = result.get("status", "sent")
            summary["status"] = status if status in ("sent", "failed") else "sent"
            summary["send_result_status"] = status
            if summary["status"] == "failed":
                if lock_key:
                    _mark_failed(lock_key)
                write_business_audit(
                    entity_type=BusinessAuditLog.ENTITY_DPR,
                    action=BusinessAuditLog.ACTION_FAILED,
                    entity_id=f"executive-digest:{date_str}",
                    detail=f"DPR executive digest send failed. source={source}",
                )
                logger.error("%s Failed inline send date=%s", _LOG, date_str)
                return summary
        else:
            future = submit_email_job(
                send_dpr_executive_digest_email,
                {
                    "report_date": date_str,
                    "recipient_ids": recipient_ids,
                },
            )
            if future is None and not getattr(settings, "DPR_EMAIL_INLINE", False):
                # Queue full — treat as failure so a later retry can recover.
                if lock_key:
                    _mark_failed(lock_key)
                summary["status"] = "failed"
                write_business_audit(
                    entity_type=BusinessAuditLog.ENTITY_DPR,
                    action=BusinessAuditLog.ACTION_FAILED,
                    entity_id=f"executive-digest:{date_str}",
                    detail=f"DPR executive digest queue full. source={source}",
                )
                logger.error("%s Queue full — not queued date=%s", _LOG, date_str)
                return summary
            summary["status"] = "queued"

        if lock_key:
            _mark_completed(lock_key)

        duration_ms = int((time.monotonic() - started) * 1000)
        summary["duration_ms"] = duration_ms

        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_DPR,
            action=BusinessAuditLog.ACTION_COMPLETED,
            entity_id=f"executive-digest:{date_str}",
            detail=(
                f"DPR executive digest triggered. "
                f"status={summary['status']} source={source} "
                f"recipient_count={recipient_count} "
                f"missing={digest.counts.projects_missing} "
                f"pending={digest.counts.pending_total}"
            ),
        )

        logger.info(
            "%s %s date=%s recipients=%s missing=%s duration_ms=%s",
            _LOG,
            "Queued" if summary["status"] == "queued" else "Completed",
            date_str,
            recipient_count,
            digest.counts.projects_missing,
            duration_ms,
        )
        return summary

    except Exception:
        duration_ms = int((time.monotonic() - started) * 1000)
        if lock_key:
            _mark_failed(lock_key)
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_DPR,
            action=BusinessAuditLog.ACTION_FAILED,
            entity_id=f"executive-digest:{date_str}",
            detail=f"DPR executive digest failed unexpectedly. source={source}",
        )
        logger.exception(
            "%s Failed date=%s source=%s duration_ms=%s",
            _LOG,
            date_str,
            source,
            duration_ms,
        )
        return {
            "status": "failed",
            "date": date_str,
            "report_date": date_str,
            "recipient_count": 0,
            "duration_ms": duration_ms,
            "source": source,
        }
