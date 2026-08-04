"""
Monthly Scope progress calculations.

Progress is always:
  (SUM of executed_quantity across valid DPR activities for the scope)
  / planned_quantity
  * 100

Never use only the latest DPR day's quantity.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum

from .models import MonthlyScopeWork

# Statuses that contribute to cumulative progress (existing business rule).
# Draft / rejected / deleted are excluded.
VALID_DPR_STATUSES = (
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
    """Bump only progress-related list/overview caches."""
    try:
        from core.cache_tags import invalidate_tags

        invalidate_tags("overview", "reports", "dashboard", "monthly_scope")
    except Exception:
        pass


class ScopeProgressService:
    """
    Service class for handling Monthly Scope progress calculations and updates.
    """

    VALID_DPR_STATUSES = VALID_DPR_STATUSES

    @staticmethod
    def _valid_activity_qs(scope):
        from dpr.models import DPRActivity

        return DPRActivity.objects.filter(
            scope=scope,
            dpr__status__in=VALID_DPR_STATUSES,
        )

    @staticmethod
    @transaction.atomic
    def update_scope_progress(scope_id, *, refresh_activities: bool = True) -> bool:
        """
        Recalculate denormalized progress for a Monthly Scope from ALL valid
        DPR activities (cumulative SUM), not the latest entry alone.
        """
        from dpr.models import DPRActivity

        try:
            scope = MonthlyScopeWork.objects.get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return False

        cumulative_data = ScopeProgressService._valid_activity_qs(scope).aggregate(
            total_executed=Sum("executed_quantity")
        )
        total_executed = cumulative_data["total_executed"] or _ZERO
        progress_percentage, remaining_quantity, total_executed = _compute_metrics(
            scope.planned_quantity, total_executed
        )

        scope.cumulative_quantity = total_executed
        scope.remaining_quantity = remaining_quantity
        scope.progress_percentage = progress_percentage

        if progress_percentage == 0:
            scope.status = "pending"
        elif progress_percentage >= 100:
            scope.status = "completed"
        else:
            scope.status = "in_progress"

        scope.save(
            update_fields=[
                "cumulative_quantity",
                "remaining_quantity",
                "progress_percentage",
                "status",
                "updated_at",
            ]
        )

        if refresh_activities:
            ScopeProgressService.refresh_activities_for_scope(scope_id)

        _invalidate_progress_caches()
        return True

    @staticmethod
    @transaction.atomic
    def refresh_activities_for_scope(scope_id) -> None:
        """
        Refresh denormalized cumulative/remaining/% on every activity for a scope.

        For each activity, cumulative = SUM(valid executed_qty where
        report_date <= this activity's report_date). Draft/rejected rows still
        get a snapshot of valid cumulative up to their date (excluding themselves
        if not valid).
        """
        from dpr.models import DPRActivity

        try:
            scope = MonthlyScopeWork.objects.get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return

        planned = scope.planned_quantity or _ZERO
        activities = list(
            DPRActivity.objects.filter(scope_id=scope_id)
            .select_related("dpr")
            .order_by("dpr__report_date", "id")
        )
        if not activities:
            return

        # Running sum of valid quantities in chronological order
        running = _ZERO
        running_by_activity_id: dict[int, Decimal] = {}
        for activity in activities:
            status = getattr(activity.dpr, "status", None)
            if status in VALID_DPR_STATUSES:
                running += _as_decimal(activity.executed_quantity)
            running_by_activity_id[activity.id] = running

        to_update: list = []
        for activity in activities:
            total = running_by_activity_id.get(activity.id, _ZERO)
            progress, remaining, total = _compute_metrics(planned, total)
            if (
                activity.cumulative_quantity != total
                or activity.remaining_quantity != remaining
                or activity.progress_percentage != progress
            ):
                activity.cumulative_quantity = total
                activity.remaining_quantity = remaining
                activity.progress_percentage = progress
                to_update.append(activity)

        if to_update:
            DPRActivity.objects.bulk_update(
                to_update,
                ["cumulative_quantity", "remaining_quantity", "progress_percentage"],
            )

    @staticmethod
    @transaction.atomic
    def update_dpr_activity_progress(activity_id) -> bool:
        """
        Recalculate the parent scope (and all sibling activities) after an
        activity create/update.
        """
        from dpr.models import DPRActivity

        try:
            activity = DPRActivity.objects.select_related("scope").get(id=activity_id)
        except DPRActivity.DoesNotExist:
            return False

        if not activity.scope_id:
            return False

        return ScopeProgressService.update_scope_progress(activity.scope_id)

    @staticmethod
    def recalculate_scopes(scope_ids) -> None:
        """Recalculate each distinct scope id (skips None/duplicates)."""
        seen: set[int] = set()
        for scope_id in scope_ids or []:
            if not scope_id or scope_id in seen:
                continue
            seen.add(scope_id)
            ScopeProgressService.update_scope_progress(scope_id)

    @staticmethod
    def recalculate_for_dpr(dpr) -> None:
        """
        Recalculate every Assigned Scope linked to a DPR.

        Call after status transitions (submit / approve / reject) and after
        activity edits so cumulative progress stays correct.
        """
        if dpr is None:
            return
        scope_ids = list(
            dpr.activities.exclude(scope_id=None).values_list("scope_id", flat=True)
        )
        ScopeProgressService.recalculate_scopes(scope_ids)

    @staticmethod
    def validate_executed_quantity(activity, executed_quantity, dpr_report_date=None):
        """
        Validate that executed quantity doesn't exceed remaining quantity.
        """
        from dpr.models import DPRActivity

        if not activity.scope:
            return True

        planned_quantity = activity.scope.planned_quantity or _ZERO

        if dpr_report_date:
            existing_cumulative = (
                DPRActivity.objects.filter(
                    scope=activity.scope,
                    dpr__report_date__lt=dpr_report_date,
                    dpr__status__in=VALID_DPR_STATUSES,
                ).aggregate(total=Sum("executed_quantity"))["total"]
                or _ZERO
            )
        else:
            existing_cumulative = (
                DPRActivity.objects.filter(
                    scope=activity.scope,
                    dpr__status__in=VALID_DPR_STATUSES,
                ).aggregate(total=Sum("executed_quantity"))["total"]
                or _ZERO
            )

        max_allowed = planned_quantity - existing_cumulative
        return _as_decimal(executed_quantity) <= max_allowed

    @staticmethod
    def get_scope_progress_summary(scope_id):
        """
        Get comprehensive progress summary for a scope.
        """
        from dpr.models import DPRActivity

        try:
            scope = MonthlyScopeWork.objects.select_related(
                "project", "category", "subcategory", "created_by", "updated_by"
            ).get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return None

        daily_progress = list(
            ScopeProgressService._valid_activity_qs(scope)
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
