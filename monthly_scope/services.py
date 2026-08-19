"""
Monthly Scope progress calculations.

Progress is always:
  (SUM of executed_quantity across all non-rejected DPR activities for the scope)
  / planned_quantity
  * 100

Never use only the latest DPR day's quantity.
Never overwrite cumulative with today's executed alone.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum
from django.utils import timezone

from .models import MonthlyScopeWork

logger = logging.getLogger("pmc.scope.progress")

# Only rejected DPRs are excluded from cumulative execution.
# Draft + pending + approved all count so Create immediately adds today's qty.
EXCLUDED_DPR_STATUSES = ("rejected",)

# Kept for callers/tests that still reference the include-list style.
VALID_DPR_STATUSES = (
    "draft",
    "approved",
    "pending_pmc_head",
    "pending_coordinator",
    "pending_team_lead",
)

_TWO_PLACES = Decimal("0.01")
_HUNDRED = Decimal("100.00")
_ZERO = Decimal("0.00")


def _as_decimal(value) -> Decimal:
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _compute_metrics(planned_quantity, total_executed) -> tuple[Decimal, Decimal, Decimal]:
    """
    Return (progress_percentage, remaining_quantity, total_executed).

    - Progress capped at 100%
    - Remaining never negative
    - Actual executed total is preserved (may exceed planned)
    """
    planned = _as_decimal(planned_quantity)
    executed = _as_decimal(total_executed)

    if planned > 0:
        raw_pct = (executed / planned) * _HUNDRED
        progress = min(raw_pct, _HUNDRED).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        remaining = max(planned - executed, _ZERO).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        progress = _ZERO
        remaining = _ZERO

    executed = executed.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return progress, remaining, executed


def _invalidate_progress_caches() -> None:
    """Bump only progress-related list/overview caches (once per batch)."""
    try:
        from core.cache_tags import invalidate_tags

        invalidate_tags("overview", "reports", "dashboard", "monthly_scope", "mpr")
    except Exception:
        pass


class ScopeProgressService:
    """
    Service class for handling Monthly Scope progress calculations and updates.
    """

    VALID_DPR_STATUSES = VALID_DPR_STATUSES
    EXCLUDED_DPR_STATUSES = EXCLUDED_DPR_STATUSES

    @staticmethod
    def _activity_qs_for_scope(scope):
        """All DPR activities for this Assigned Scope except rejected DPRs."""
        from dpr.models import DPRActivity

        return DPRActivity.objects.filter(scope=scope).exclude(
            dpr__status__in=EXCLUDED_DPR_STATUSES
        )

    @staticmethod
    def _breakdown_for_scope(scope) -> dict:
        """
        Build an audit breakdown of every activity contributing to cumulative.
        Used for debug logging only — not on the write hot path.
        """
        from dpr.models import DPRActivity

        rows = list(
            DPRActivity.objects.filter(scope=scope)
            .select_related("dpr")
            .order_by("dpr__report_date", "id")
            .values(
                "id",
                "executed_quantity",
                "dpr_id",
                "dpr__report_date",
                "dpr__status",
            )
        )
        included = []
        excluded = []
        total = _ZERO
        for row in rows:
            status = row["dpr__status"]
            qty = _as_decimal(row["executed_quantity"])
            entry = {
                "activity_id": row["id"],
                "dpr_id": row["dpr_id"],
                "report_date": str(row["dpr__report_date"]),
                "status": status,
                "executed_quantity": str(qty),
            }
            if status in EXCLUDED_DPR_STATUSES:
                excluded.append(entry)
            else:
                included.append(entry)
                total += qty
        return {
            "included": included,
            "excluded": excluded,
            "aggregated_executed": total,
        }

    @staticmethod
    def _unique_scope_ids(scope_ids) -> list[int]:
        seen: set[int] = set()
        unique: list[int] = []
        for scope_id in scope_ids or []:
            if not scope_id or scope_id in seen:
                continue
            seen.add(scope_id)
            unique.append(int(scope_id))
        return unique

    @staticmethod
    def _apply_scope_status(scope, progress_percentage: Decimal) -> None:
        if progress_percentage == 0:
            scope.status = "pending"
        elif progress_percentage >= 100:
            scope.status = "completed"
        else:
            scope.status = "in_progress"

    @staticmethod
    def _recalculate_scopes_bulk(
        scope_ids: list[int],
        *,
        refresh_activities: bool = True,
        scopes_by_id: dict | None = None,
    ) -> list:
        """
        Recalculate many scopes with the same formulas as update_scope_progress,
        using one activity query and one scope query, then bulk_update.

        Returns the activity rows loaded for those scopes (used to avoid a
        second prefetch on DPR serialize).
        """
        from dpr.models import DPRActivity

        if not scope_ids:
            return []

        if scopes_by_id:
            missing = [sid for sid in scope_ids if sid not in scopes_by_id]
            scopes = {sid: scopes_by_id[sid] for sid in scope_ids if sid in scopes_by_id}
            if missing:
                for scope in MonthlyScopeWork.objects.filter(id__in=missing):
                    scopes[scope.id] = scope
        else:
            scopes = {
                scope.id: scope
                for scope in MonthlyScopeWork.objects.filter(id__in=scope_ids)
            }
        activities = list(
            DPRActivity.objects.filter(scope_id__in=scope_ids)
            .select_related("dpr")
            .order_by("scope_id", "dpr__report_date", "id")
        )
        by_scope: dict[int, list] = defaultdict(list)
        for activity in activities:
            by_scope[activity.scope_id].append(activity)

        now = timezone.now()
        scopes_to_update: list = []
        activities_to_update: list = []

        for scope_id in scope_ids:
            scope = scopes.get(scope_id)
            if scope is None:
                continue

            planned_quantity = scope.planned_quantity or _ZERO
            previous_cumulative = _as_decimal(scope.cumulative_quantity)
            rows = by_scope.get(scope_id, [])

            running = _ZERO
            total_executed = _ZERO
            running_by_activity_id: dict[int, Decimal] = {}
            included_count = 0
            excluded_count = 0
            for activity in rows:
                status = getattr(activity.dpr, "status", None)
                qty = _as_decimal(activity.executed_quantity)
                if status not in EXCLUDED_DPR_STATUSES:
                    running += qty
                    total_executed += qty
                    included_count += 1
                else:
                    excluded_count += 1
                running_by_activity_id[activity.id] = running

            progress_percentage, remaining_quantity, total_executed = _compute_metrics(
                planned_quantity, total_executed
            )
            today_delta = total_executed - previous_cumulative

            logger.info(
                "scope_progress_recalc scope_id=%s planned=%s previous_cumulative=%s "
                "today_delta≈%s aggregated_executed=%s progress=%s%% remaining=%s "
                "included_count=%s excluded_count=%s",
                scope_id,
                planned_quantity,
                previous_cumulative,
                today_delta,
                total_executed,
                progress_percentage,
                remaining_quantity,
                included_count,
                excluded_count,
            )

            ScopeProgressService._apply_scope_status(scope, progress_percentage)
            # Always persist so status/updated_at stay in sync with the prior save() path.
            scope.cumulative_quantity = total_executed
            scope.remaining_quantity = remaining_quantity
            scope.progress_percentage = progress_percentage
            scope.updated_at = now
            scopes_to_update.append(scope)

            if not refresh_activities:
                continue

            for activity in rows:
                total = running_by_activity_id.get(activity.id, _ZERO)
                progress, remaining, total = _compute_metrics(planned_quantity, total)
                qty_today = _as_decimal(activity.executed_quantity)
                logger.debug(
                    "activity_progress_recalc activity_id=%s dpr_id=%s status=%s "
                    "todays_executed=%s running_cumulative=%s planned=%s progress=%s%%",
                    activity.id,
                    activity.dpr_id,
                    getattr(activity.dpr, "status", None),
                    qty_today,
                    total,
                    planned_quantity,
                    progress,
                )
                if (
                    activity.cumulative_quantity != total
                    or activity.remaining_quantity != remaining
                    or activity.progress_percentage != progress
                ):
                    activity.cumulative_quantity = total
                    activity.remaining_quantity = remaining
                    activity.progress_percentage = progress
                    activities_to_update.append(activity)

        if scopes_to_update:
            MonthlyScopeWork.objects.bulk_update(
                scopes_to_update,
                [
                    "cumulative_quantity",
                    "remaining_quantity",
                    "progress_percentage",
                    "status",
                    "updated_at",
                ],
            )
        if activities_to_update:
            DPRActivity.objects.bulk_update(
                activities_to_update,
                ["cumulative_quantity", "remaining_quantity", "progress_percentage"],
            )

        _invalidate_progress_caches()
        return activities

    @staticmethod
    def update_scope_progress(scope_id, *, refresh_activities: bool = True) -> bool:
        """
        Recalculate denormalized progress for a Monthly Scope from ALL
        non-rejected DPR activities linked to that Assigned Scope (SUM).
        """
        unique = ScopeProgressService._unique_scope_ids([scope_id])
        if not unique:
            return False
        from core.cache_tags import batch_cache_invalidation

        with batch_cache_invalidation():
            return bool(
                ScopeProgressService._recalculate_scopes_bulk(
                    unique,
                    refresh_activities=refresh_activities,
                )
            )

    @staticmethod
    def refresh_activities_for_scope(scope_id) -> None:
        """
        Refresh denormalized cumulative/remaining/% on every activity for a scope.

        For each activity, cumulative = SUM(non-rejected executed_qty where
        report_date <= this activity's report_date). Rejected rows keep a
        snapshot of valid cumulative up to their date (excluding themselves).
        """
        ScopeProgressService.update_scope_progress(scope_id, refresh_activities=True)

    @staticmethod
    def update_dpr_activity_progress(activity_id) -> bool:
        """
        Recalculate the parent scope (and all sibling activities) after an
        activity create/update.
        """
        from dpr.models import DPRActivity

        try:
            activity = (
                DPRActivity.objects.select_related("scope", "dpr").get(id=activity_id)
            )
        except DPRActivity.DoesNotExist:
            return False

        if not activity.scope_id:
            return False

        logger.info(
            "update_dpr_activity_progress activity_id=%s scope_id=%s "
            "todays_executed=%s dpr_status=%s",
            activity.id,
            activity.scope_id,
            activity.executed_quantity,
            getattr(activity.dpr, "status", None),
        )
        return ScopeProgressService.update_scope_progress(activity.scope_id)

    @staticmethod
    def recalculate_scopes(scope_ids, scopes_by_id: dict | None = None) -> list:
        """Recalculate each distinct scope id (skips None/duplicates)."""
        unique = ScopeProgressService._unique_scope_ids(scope_ids)
        if not unique:
            return []
        from core.cache_tags import batch_cache_invalidation

        with batch_cache_invalidation():
            return ScopeProgressService._recalculate_scopes_bulk(
                unique,
                scopes_by_id=scopes_by_id,
            )

    @staticmethod
    def recalculate_for_dpr(dpr, *, scope_ids=None, scopes_by_id: dict | None = None) -> list:
        """
        Recalculate every Assigned Scope linked to a DPR.

        Call after Create / Update / Delete / Submit / Approve / Reject.
        Pass scope_ids when the caller already knows them to skip a values_list query.
        """
        if dpr is None:
            return []
        if scope_ids is None:
            scope_ids = list(
                dpr.activities.exclude(scope_id=None).values_list("scope_id", flat=True)
            )
        logger.info(
            "recalculate_for_dpr dpr_id=%s status=%s scope_ids=%s",
            getattr(dpr, "id", None),
            getattr(dpr, "status", None),
            scope_ids,
        )
        return ScopeProgressService.recalculate_scopes(scope_ids, scopes_by_id=scopes_by_id)

    @staticmethod
    def validate_executed_quantity(activity, executed_quantity, dpr_report_date=None):
        """
        Validate that executed quantity doesn't exceed remaining quantity.
        """
        from dpr.models import DPRActivity

        if not activity.scope:
            return True

        planned_quantity = activity.scope.planned_quantity or _ZERO

        qs = DPRActivity.objects.filter(scope=activity.scope).exclude(
            dpr__status__in=EXCLUDED_DPR_STATUSES
        )
        if dpr_report_date:
            qs = qs.filter(dpr__report_date__lt=dpr_report_date)
        # When validating an existing row, exclude itself from prior total
        if getattr(activity, "pk", None):
            qs = qs.exclude(pk=activity.pk)

        existing_cumulative = qs.aggregate(total=Sum("executed_quantity"))["total"] or _ZERO
        max_allowed = planned_quantity - existing_cumulative
        return _as_decimal(executed_quantity) <= max_allowed

    @staticmethod
    def get_scope_progress_summary(scope_id):
        """
        Get comprehensive progress summary for a scope.
        Always re-aggregates from DPR activities (not a stale cache read).
        """
        from dpr.models import DPRActivity

        try:
            scope = MonthlyScopeWork.objects.select_related(
                "project", "category", "subcategory", "created_by", "updated_by"
            ).get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return None

        # Live recompute so progress API never returns a stale denormalized value
        ScopeProgressService.update_scope_progress(scope_id, refresh_activities=True)
        scope.refresh_from_db()

        daily_progress = list(
            ScopeProgressService._activity_qs_for_scope(scope)
            .select_related("dpr")
            .order_by("dpr__report_date")
            .values(
                "executed_quantity",
                "cumulative_quantity",
                "progress_percentage",
                "dpr__report_date",
            )
        )

        latest_dpr = (
            DPRActivity.objects.filter(scope=scope)
            .select_related("dpr")
            .order_by("-dpr__report_date")
            .first()
        )

        logger.info(
            "scope_progress_summary_response scope_id=%s planned=%s "
            "aggregated_executed=%s progress=%s%%",
            scope_id,
            scope.planned_quantity,
            scope.cumulative_quantity,
            scope.progress_percentage,
        )

        return {
            "scope": scope,
            "planned_quantity": scope.planned_quantity,
            "executed_quantity": scope.cumulative_quantity,
            "remaining_quantity": scope.remaining_quantity,
            "progress_percentage": scope.progress_percentage,
            "status": scope.status,
            "daily_progress": daily_progress,
            "latest_dpr_date": latest_dpr.dpr.report_date if latest_dpr else None,
            "total_dpr_entries": len(daily_progress),
        }
