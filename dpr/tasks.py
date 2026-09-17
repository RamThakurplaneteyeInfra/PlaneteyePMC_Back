"""
In-process async DPR SMTP emails (WebSockets stay in-request).

Uses a shared ThreadPoolExecutor after transaction.on_commit — no Celery worker.
See dpr.email_executor for pool metrics, shutdown, and submit helpers.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections, transaction

from celery import shared_task

from dpr.email_executor import (
    EMAIL_EXECUTOR,  # noqa: F401 — re-export for tests / callers
    get_email_pool_snapshot,  # noqa: F401
    submit_email_job,
)
from services.email_utils import is_retryable_smtp_error

logger = logging.getLogger("pmc.dpr.email")
User = get_user_model()

_LOG = "[DPR Email]"
_DEDUP_TTL_SECONDS = 300
_MAX_ATTEMPTS = 3
_RETRY_DELAYS_SEC = (1, 2, 4)


def _dedup_key(kind: str, dpr_id: int, recipient_ids: list[int], extra: str = "") -> str:
    ids = "-".join(str(i) for i in sorted(recipient_ids or []))
    extra_clean = (extra or "").replace(" ", "_")
    return f"dpr:{kind}:{dpr_id}:{ids}:{extra_clean}"


def _acquire_dedup(key: str) -> bool:
    return bool(cache.add(key, "1", timeout=_DEDUP_TTL_SECONDS))


def _release_dedup(key: str) -> None:
    cache.delete(key)


def _resolve_project(project_name: str):
    from projects.models import Project

    clean = (project_name or "").strip()
    project = Project.objects.filter(name__iexact=clean).first()
    if not project and clean:
        project = Project.objects.filter(name__icontains=clean).first()
    return project


def _load_dpr(dpr_id: int):
    from dpr.models import DailyProgressReport

    return (
        DailyProgressReport.objects.select_related(
            "submitted_by", "approved_by", "rejected_by"
        )
        .filter(pk=dpr_id)
        .first()
    )


def _users_with_email(recipient_ids: list[int]) -> list:
    return list(
        User.objects.filter(id__in=recipient_ids or [], is_active=True).exclude(email="")
    )


def _user_payload(user) -> dict[str, str] | None:
    if not user:
        return None
    return {
        "username": user.username or "Unknown",
        "get_full_name": user.get_full_name() or "Unknown User",
    }


def _send_smtp(*, subject: str, template_name: str, context: dict, recipient_emails: list[str]) -> None:
    from services.email_utils import send_html_email

    logger.info("%s SMTP template=%s recipient_count=%s", _LOG, template_name, len(recipient_emails))
    ok = send_html_email(
        subject=subject,
        template_name=template_name,
        context=context,
        recipient_list=recipient_emails,
    )
    if not ok:
        raise RuntimeError(f"SMTP send_html_email returned failure template={template_name}")


def _run_email_job(
    *,
    kind: str,
    dpr_id: int,
    recipient_ids: list[int],
    build_context_and_subject: Callable,
    extra_dedup: str = "",
) -> dict[str, Any]:
    """
    Fetch fresh DB rows by ID, send SMTP with retries (1s / 2s / 4s).
    Dedup lock held for the whole attempt cycle so retries never double-send.
    """
    recipient_ids = list(recipient_ids or [])
    dedup = _dedup_key(kind, dpr_id, recipient_ids, extra_dedup)
    send_ms_total = 0.0

    if not _acquire_dedup(dedup):
        logger.info("%s Skipped duplicate kind=%s dpr_id=%s", _LOG, kind, dpr_id)
        return {"status": "skipped_duplicate", "dpr_id": dpr_id, "kind": kind}

    thread_db = not getattr(settings, "DPR_EMAIL_INLINE", False)
    if thread_db:
        close_old_connections()

    dpr = None
    project = None
    recipients = None
    context = None
    try:
        dpr = _load_dpr(dpr_id)
        if dpr is None:
            logger.error("%s Email Failed DPR not found kind=%s dpr_id=%s", _LOG, kind, dpr_id)
            return {"status": "dpr_not_found", "dpr_id": dpr_id, "kind": kind}

        recipients = _users_with_email(recipient_ids)
        recipient_emails = []
        seen_emails: set[str] = set()
        for user in recipients:
            email = (user.email or "").strip()
            key = email.lower()
            if not email or key in seen_emails:
                continue
            seen_emails.add(key)
            recipient_emails.append(email)
        if not recipient_emails:
            logger.warning(
                "%s Email Failed no recipients kind=%s dpr_id=%s",
                _LOG,
                kind,
                dpr_id,
            )
            return {"status": "no_recipients", "dpr_id": dpr_id, "kind": kind}

        project = _resolve_project(dpr.project_name)
        subject, template_name, context = build_context_and_subject(
            dpr=dpr, project=project, recipients=recipients
        )

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                logger.info(
                    "%s Sending email kind=%s dpr_id=%s attempt=%s/%s recipient_count=%s",
                    _LOG,
                    kind,
                    dpr_id,
                    attempt,
                    _MAX_ATTEMPTS,
                    len(recipient_emails),
                )
                smtp_started_at = time.perf_counter()
                _send_smtp(
                    subject=subject,
                    template_name=template_name,
                    context=context,
                    recipient_emails=recipient_emails,
                )
                elapsed_ms = (time.perf_counter() - smtp_started_at) * 1000.0
                send_ms_total += elapsed_ms
                logger.info(
                    "%s Sent kind=%s dpr_id=%s attempt=%s smtp_time_ms=%.1f",
                    _LOG,
                    kind,
                    dpr_id,
                    attempt,
                    elapsed_ms,
                )
                return {
                    "status": "sent",
                    "dpr_id": dpr_id,
                    "kind": kind,
                    "recipient_count": len(recipient_emails),
                    "attempts": attempt,
                    "send_ms": round(send_ms_total, 2),
                    "smtp_time_ms": round(elapsed_ms, 2),
                }
            except Exception as exc:
                last_exc = exc
                retryable = is_retryable_smtp_error(exc)
                if retryable and attempt < _MAX_ATTEMPTS:
                    delay = _RETRY_DELAYS_SEC[attempt - 1]
                    logger.warning(
                        "%s Retry %s kind=%s dpr_id=%s delay_sec=%s err_type=%s",
                        _LOG,
                        attempt,
                        kind,
                        dpr_id,
                        delay,
                        type(exc).__name__,
                    )
                    time.sleep(delay)
                    continue
                logger.exception(
                    "%s Failed kind=%s dpr_id=%s attempts=%s retryable=%s err_type=%s",
                    _LOG,
                    kind,
                    dpr_id,
                    attempt,
                    retryable,
                    type(exc).__name__,
                )
                _release_dedup(dedup)
                return {
                    "status": "failed",
                    "dpr_id": dpr_id,
                    "kind": kind,
                    "error": type(last_exc).__name__ if last_exc else "error",
                    "send_ms": round(send_ms_total, 2),
                    "attempts": attempt,
                    "retryable": retryable,
                }

        return {
            "status": "failed",
            "dpr_id": dpr_id,
            "kind": kind,
            "error": type(last_exc).__name__ if last_exc else "error",
            "send_ms": round(send_ms_total, 2),
        }
    finally:
        dpr = None
        project = None
        recipients = None
        context = None
        if thread_db:
            close_old_connections()


def queue_after_commit(
    fn: Callable,
    *,
    log_label: str | None = None,
    log_dpr_id: int | None = None,
    log_is_resubmit: bool | None = None,
    log_status: str | None = None,
    **kwargs,
) -> str:
    """
    After DB commit, run ``fn(**kwargs)`` on EMAIL_EXECUTOR (or inline in tests).

    Pass only lightweight IDs in kwargs — never Django model instances.
    Returns a lightweight job_id string for structured logs (not a Future).
    """
    job_id = f"{getattr(fn, '__name__', 'email')}-{int(time.time() * 1000)}"

    def _enqueue():
        if log_label:
            logger.info(
                "%s %s dpr_id=%s is_resubmit=%s status=%s job_id=%s",
                _LOG,
                log_label,
                log_dpr_id,
                log_is_resubmit,
                log_status,
                job_id,
            )
        else:
            logger.info(
                "%s Queued fn=%s job_id=%s kwargs_keys=%s",
                _LOG,
                getattr(fn, "__name__", str(fn)),
                job_id,
                sorted(kwargs.keys()),
            )
        submit_email_job(fn, kwargs)

    transaction.on_commit(_enqueue)
    return job_id


def run_background_smtp_job(*, kind: str, dedup_key: str, send_fn: Callable) -> dict[str, Any]:
    """
    Retry/dedup wrapper for non-DPR SMTP workers (project created/assigned).
    send_fn must raise on SMTP failure; return value is ignored.
    """
    send_ms_total = 0.0
    if not _acquire_dedup(dedup_key):
        logger.info("%s Skipped duplicate kind=%s", _LOG, kind)
        return {"status": "skipped_duplicate", "kind": kind}

    thread_db = not getattr(settings, "DPR_EMAIL_INLINE", False)
    if thread_db:
        close_old_connections()
    last_exc: Exception | None = None
    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                logger.info(
                    "%s Sending email kind=%s attempt=%s/%s",
                    _LOG,
                    kind,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                smtp_started_at = time.perf_counter()
                send_fn()
                elapsed_ms = (time.perf_counter() - smtp_started_at) * 1000.0
                send_ms_total += elapsed_ms
                logger.info(
                    "%s Sent kind=%s attempt=%s smtp_time_ms=%.1f",
                    _LOG,
                    kind,
                    attempt,
                    elapsed_ms,
                )
                return {
                    "status": "sent",
                    "kind": kind,
                    "attempts": attempt,
                    "send_ms": round(send_ms_total, 2),
                    "smtp_time_ms": round(elapsed_ms, 2),
                }
            except Exception as exc:
                last_exc = exc
                retryable = is_retryable_smtp_error(exc)
                if retryable and attempt < _MAX_ATTEMPTS:
                    delay = _RETRY_DELAYS_SEC[attempt - 1]
                    logger.warning(
                        "%s Retry %s kind=%s delay_sec=%s err_type=%s",
                        _LOG,
                        attempt,
                        kind,
                        delay,
                        type(exc).__name__,
                    )
                    time.sleep(delay)
                    continue
                logger.exception(
                    "%s Failed kind=%s attempts=%s retryable=%s err_type=%s",
                    _LOG,
                    kind,
                    attempt,
                    retryable,
                    type(exc).__name__,
                )
                _release_dedup(dedup_key)
                return {
                    "status": "failed",
                    "kind": kind,
                    "error": type(last_exc).__name__,
                    "send_ms": round(send_ms_total, 2),
                    "attempts": attempt,
                    "retryable": retryable,
                }
        return {
            "status": "failed",
            "kind": kind,
            "error": type(last_exc).__name__ if last_exc else "error",
            "send_ms": round(send_ms_total, 2),
        }
    finally:
        if thread_db:
            close_old_connections()


# ---------------------------------------------------------------------------
# Submission / resubmission
# ---------------------------------------------------------------------------


def _build_submission(dpr, project, recipients):
    submitted_by = dpr.submitted_by
    context = {
        "dpr": {
            "project_name": dpr.project_name,
            "report_date": dpr.report_date.isoformat() if dpr.report_date else "",
            "job_no": dpr.job_no,
            "issued_by": dpr.issued_by,
            "designation": dpr.designation,
            "submitted_by": _user_payload(submitted_by),
        },
        "project": {
            "name": project.name if project else dpr.project_name,
            "client_name": getattr(project, "client_name", "") if project else "",
            "location": getattr(project, "location", "") if project else "",
        },
        "approver": {
            "username": recipients[0].username,
            "get_full_name": recipients[0].get_full_name(),
        }
        if recipients
        else None,
    }
    subject = f"DPR Submitted for Approval: {dpr.project_name} - {dpr.report_date}"
    return subject, "dpr_submitted", context


def send_dpr_submission_email(
    dpr_id: int,
    submitted_by_id: int | None = None,
    recipient_ids: list[int] | None = None,
    **_kwargs,
) -> dict:
    return _run_email_job(
        kind="submit_email",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
        build_context_and_subject=_build_submission,
    )


def send_dpr_resubmission_email(
    dpr_id: int,
    submitted_by_id: int | None = None,
    recipient_ids: list[int] | None = None,
    **_kwargs,
) -> dict:
    """Same content as submission; separate dedup key for resubmit after reject."""
    return _run_email_job(
        kind="resubmit_email",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
        build_context_and_subject=_build_submission,
    )


# ---------------------------------------------------------------------------
# Role-based approval
# ---------------------------------------------------------------------------


def _build_approval_by_role(approved_by_role: str):
    def _builder(dpr, project, recipients):
        context = {
            "dpr": {
                "project_name": dpr.project_name,
                "report_date": dpr.report_date.isoformat() if dpr.report_date else "",
                "job_no": dpr.job_no,
                "status": "Approved",
                "approved_at": dpr.approved_at.isoformat() if dpr.approved_at else None,
                "approved_by": _user_payload(dpr.approved_by),
            },
            "project": {"name": project.name if project else dpr.project_name},
            "submitter": _user_payload(dpr.submitted_by) or {
                "username": "Unknown",
                "get_full_name": "Unknown User",
            },
            "approved_by_role": approved_by_role,
        }
        subject = (
            f"DPR Approved by {approved_by_role}: {dpr.project_name} - {dpr.report_date}"
        )
        return subject, "dpr_approved", context

    return _builder


def _approval_job(*, role: str, kind: str, dpr_id: int, recipient_ids: list[int]) -> dict:
    return _run_email_job(
        kind=kind,
        dpr_id=dpr_id,
        recipient_ids=recipient_ids,
        build_context_and_subject=_build_approval_by_role(role),
        extra_dedup=role,
    )


def send_dpr_team_leader_approval_email(
    dpr_id: int, recipient_ids: list[int] | None = None, **_kwargs
) -> dict:
    return _approval_job(
        role="Team Leader",
        kind="approval_tl",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
    )


def send_dpr_coordinator_approval_email(
    dpr_id: int, recipient_ids: list[int] | None = None, **_kwargs
) -> dict:
    return _approval_job(
        role="PMC Manager",
        kind="approval_coordinator",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
    )


def send_dpr_pmc_head_approval_email(
    dpr_id: int, recipient_ids: list[int] | None = None, **_kwargs
) -> dict:
    return _approval_job(
        role="PMC Head",
        kind="approval_pmc_head",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
    )


# ---------------------------------------------------------------------------
# Role-based rejection
# ---------------------------------------------------------------------------


def _build_rejection_by_role(rejected_by_role: str):
    def _builder(dpr, project, recipients):
        context = {
            "dpr": {
                "project_name": dpr.project_name,
                "report_date": dpr.report_date.isoformat() if dpr.report_date else "",
                "job_no": dpr.job_no,
                "status": "Rejected",
                "rejection_reason": dpr.rejection_reason,
                "rejected_by": _user_payload(dpr.rejected_by),
            },
            "project": {"name": project.name if project else dpr.project_name},
            "submitter": _user_payload(dpr.submitted_by) or {
                "username": "Unknown",
                "get_full_name": "Unknown User",
            },
            "rejected_by_role": rejected_by_role,
        }
        subject = (
            f"DPR Rejected by {rejected_by_role}: {dpr.project_name} - {dpr.report_date}"
        )
        return subject, "dpr_rejected", context

    return _builder


def send_dpr_rejection_email(
    dpr_id: int,
    recipient_ids: list[int] | None = None,
    role: str = "",
    **_kwargs,
) -> dict:
    role = role or "Unknown"
    return _run_email_job(
        kind="rejection",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
        build_context_and_subject=_build_rejection_by_role(role),
        extra_dedup=role,
    )


# ---------------------------------------------------------------------------
# Legacy simple approve / reject (submitter only)
# ---------------------------------------------------------------------------


def _build_legacy_approved(dpr, project, recipients):
    context = {
        "dpr": {
            "project_name": dpr.project_name,
            "report_date": dpr.report_date.isoformat() if dpr.report_date else "",
            "job_no": dpr.job_no,
            "status": "Approved",
            "approved_at": dpr.approved_at.isoformat() if dpr.approved_at else None,
            "approved_by": _user_payload(dpr.approved_by),
        },
        "project": {"name": project.name if project else dpr.project_name},
        "submitter": _user_payload(dpr.submitted_by) or {
            "username": "Unknown",
            "get_full_name": "Unknown User",
        },
    }
    subject = f"DPR Approved: {dpr.project_name} - {dpr.report_date}"
    return subject, "dpr_approved", context


def _build_legacy_rejected(dpr, project, recipients):
    context = {
        "dpr": {
            "project_name": dpr.project_name,
            "report_date": dpr.report_date.isoformat() if dpr.report_date else "",
            "job_no": dpr.job_no,
            "status": "Rejected",
            "rejection_reason": dpr.rejection_reason,
            "rejected_by": _user_payload(dpr.rejected_by),
        },
        "project": {"name": project.name if project else dpr.project_name},
        "submitter": _user_payload(dpr.submitted_by) or {
            "username": "Unknown",
            "get_full_name": "Unknown User",
        },
    }
    subject = f"DPR Rejected: {dpr.project_name} - {dpr.report_date}"
    return subject, "dpr_rejected", context


def send_dpr_approved_email(
    dpr_id: int, recipient_ids: list[int] | None = None, **_kwargs
) -> dict:
    return _run_email_job(
        kind="legacy_approved",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
        build_context_and_subject=_build_legacy_approved,
    )


def send_dpr_rejected_email(
    dpr_id: int, recipient_ids: list[int] | None = None, **_kwargs
) -> dict:
    return _run_email_job(
        kind="legacy_rejected",
        dpr_id=dpr_id,
        recipient_ids=list(recipient_ids or []),
        build_context_and_subject=_build_legacy_rejected,
    )


def approval_task_for_role(approved_by_role: str):
    """Map workflow role → approval email job (same name kept for call sites)."""
    if approved_by_role == "Team Leader":
        return send_dpr_team_leader_approval_email
    if approved_by_role in ("PMC Manager", "Coordinator"):
        return send_dpr_coordinator_approval_email
    if approved_by_role == "PMC Head":
        return send_dpr_pmc_head_approval_email
    return send_dpr_coordinator_approval_email


def send_dpr_executive_digest_email(
    *,
    report_date: str,
    recipient_ids: list[int] | None = None,
    **_kwargs,
) -> dict[str, Any]:
    """
    Send the PMC Head / Head Office DPR summary for one report date.

    ``report_date`` is ISO YYYY-MM-DD. Safe to call from cron (no on_commit).
    Marks digest idempotency completed/failed after SMTP/Brevo attempt.
    """
    from datetime import date as date_cls

    from dpr.services.digest import build_executive_digest
    from dpr.services.executive_digest import mark_digest_send_result
    from services.email_utils import send_html_email

    recipient_ids = list(recipient_ids or [])
    thread_db = not getattr(settings, "DPR_EMAIL_INLINE", False)
    if thread_db:
        close_old_connections()

    try:
        parsed = date_cls.fromisoformat(report_date)
        digest = build_executive_digest(report_date=parsed)
        recipients = _users_with_email(recipient_ids)
        if not recipients:
            logger.warning("%s Digest skipped — no recipients date=%s", _LOG, report_date)
            mark_digest_send_result(report_date, success=False)
            return {"status": "skipped_no_recipients", "report_date": report_date}

        context = digest.to_context()
        subject = (
            f"DPR Executive Digest — {digest.report_date.strftime('%d %b %Y')} "
            f"({digest.counts.projects_missing} missing, "
            f"{digest.counts.pending_total} pending)"
        )
        emails = [u.email for u in recipients]
        logger.info(
            "%s SMTP/Brevo attempt date=%s subject=%s recipient_count=%s",
            _LOG,
            report_date,
            subject,
            len(emails),
        )
        # One mail to the leadership group (same summary for all).
        context["recipient_name"] = "PMC Leadership"
        send_html_email(
            subject=subject,
            template_name="dpr_executive_digest",
            context=context,
            recipient_list=emails,
        )
        mark_digest_send_result(report_date, success=True)
        logger.info(
            "%s Digest sent date=%s recipients=%s missing=%s pending=%s",
            _LOG,
            report_date,
            len(emails),
            digest.counts.projects_missing,
            digest.counts.pending_total,
        )
        return {
            "status": "sent",
            "report_date": report_date,
            "recipient_count": len(emails),
            "missing": digest.counts.projects_missing,
            "pending": digest.counts.pending_total,
            "filled": digest.counts.total_filled,
        }
    except Exception:
        logger.exception("%s Digest email worker failed date=%s", _LOG, report_date)
        try:
            mark_digest_send_result(report_date, success=False)
        except Exception:
            logger.exception("%s Failed to mark digest failed date=%s", _LOG, report_date)
        return {
            "status": "failed",
            "report_date": report_date,
            "error": "send_failed",
        }
    finally:
        if thread_db:
            close_old_connections()


@shared_task(name="dpr.send_executive_digest")
def send_executive_digest_task(report_date: str | None = None) -> dict:
    """
    Celery entrypoint — delegates to the shared executive digest service.
    Preferred production trigger: POST /api/internal/dpr/executive-digest/
    """
    from datetime import date as date_cls

    from dpr.services.executive_digest import send_dpr_executive_digest

    parsed = date_cls.fromisoformat(report_date) if report_date else None
    return send_dpr_executive_digest(
        report_date=parsed,
        source="celery_task",
    )
