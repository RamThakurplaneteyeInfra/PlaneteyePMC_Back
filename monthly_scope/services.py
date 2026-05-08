from django.db import transaction
from django.db.models import Sum, F, Q
from decimal import Decimal
from .models import MonthlyScopeWork


class ScopeProgressService:
    """
    Service class for handling Monthly Scope progress calculations and updates
    """

    @staticmethod
    @transaction.atomic
    def update_scope_progress(scope_id):
        from dpr.models import DPRActivity
        """
        Update progress for a specific Monthly Scope based on all DPR activities
        """
        try:
            scope = MonthlyScopeWork.objects.get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return False

        # Calculate cumulative executed quantity
        cumulative_data = DPRActivity.objects.filter(
            scope=scope,
            dpr__status__in=['approved', 'pending_pmc_head', 'pending_coordinator', 'pending_team_lead']
        ).aggregate(
            total_executed=Sum('executed_quantity')
        )

        total_executed = cumulative_data['total_executed'] or Decimal('0.00')
        planned_quantity = scope.planned_quantity or Decimal('0.00')

        # Calculate progress metrics
        if planned_quantity > 0:
            progress_percentage = (total_executed / planned_quantity) * 100
            remaining_quantity = planned_quantity - total_executed
        else:
            progress_percentage = Decimal('0.00')
            remaining_quantity = Decimal('0.00')

        # Ensure progress doesn't exceed 100%
        progress_percentage = min(progress_percentage, Decimal('100.00'))
        remaining_quantity = max(remaining_quantity, Decimal('0.00'))

        # Update scope
        scope.cumulative_quantity = total_executed
        scope.remaining_quantity = remaining_quantity
        scope.progress_percentage = progress_percentage

        # Update status based on progress
        if progress_percentage == 0:
            scope.status = 'pending'
        elif progress_percentage >= 100:
            scope.status = 'completed'
        else:
            scope.status = 'in_progress'

        scope.save(update_fields=[
            'cumulative_quantity', 'remaining_quantity',
            'progress_percentage', 'status', 'updated_at'
        ])

        return True

    @staticmethod
    @transaction.atomic
    def update_dpr_activity_progress(activity_id):
        """
        Update progress calculations for a specific DPR activity
        """
        from dpr.models import DPRActivity

        try:
            activity = DPRActivity.objects.select_related('scope').get(id=activity_id)
        except DPRActivity.DoesNotExist:
            return False

        if not activity.scope:
            return False

        # Calculate cumulative quantity for this scope up to this DPR's report date
        cumulative_data = DPRActivity.objects.filter(
            scope=activity.scope,
            dpr__report_date__lte=activity.dpr.report_date,
            dpr__status__in=['approved', 'pending_pmc_head', 'pending_coordinator', 'pending_team_lead']
        ).aggregate(
            total_executed=Sum('executed_quantity')
        )

        total_executed = cumulative_data['total_executed'] or Decimal('0.00')
        planned_quantity = activity.scope.planned_quantity or Decimal('0.00')

        # Update activity progress fields
        if planned_quantity > 0:
            progress_percentage = (total_executed / planned_quantity) * 100
            remaining_quantity = planned_quantity - total_executed
        else:
            progress_percentage = Decimal('0.00')
            remaining_quantity = Decimal('0.00')

        # Ensure bounds
        progress_percentage = min(progress_percentage, Decimal('100.00'))
        remaining_quantity = max(remaining_quantity, Decimal('0.00'))

        activity.cumulative_quantity = total_executed
        activity.remaining_quantity = remaining_quantity
        activity.progress_percentage = progress_percentage
        activity.save(update_fields=[
            'cumulative_quantity', 'remaining_quantity', 'progress_percentage'
        ])

        # Update the scope progress
        ScopeProgressService.update_scope_progress(activity.scope.id)

        return True

    @staticmethod
    def validate_executed_quantity(activity, executed_quantity, dpr_report_date=None):
        """
        Validate that executed quantity doesn't exceed remaining quantity
        """
        from dpr.models import DPRActivity

        if not activity.scope:
            return True

        # For validation before creation, check against total planned quantity
        # (since we don't know the exact date filtering yet)
        planned_quantity = activity.scope.planned_quantity or Decimal('0.00')

        # If we have a DPR report date, use date-based filtering
        if dpr_report_date:
            existing_cumulative = DPRActivity.objects.filter(
                scope=activity.scope,
                dpr__report_date__lt=dpr_report_date,
                dpr__status__in=['approved', 'pending_pmc_head', 'pending_coordinator', 'pending_team_lead']
            ).aggregate(
                total=Sum('executed_quantity')
            )['total'] or Decimal('0.00')
        else:
            # For pre-creation validation, use all existing activities
            existing_cumulative = DPRActivity.objects.filter(
                scope=activity.scope,
                dpr__status__in=['approved', 'pending_pmc_head', 'pending_coordinator', 'pending_team_lead']
            ).aggregate(
                total=Sum('executed_quantity')
            )['total'] or Decimal('0.00')

        max_allowed = planned_quantity - existing_cumulative
        return executed_quantity <= max_allowed

    @staticmethod
    def get_scope_progress_summary(scope_id):
        """
        Get comprehensive progress summary for a scope
        """
        from dpr.models import DPRActivity

        try:
            scope = MonthlyScopeWork.objects.select_related(
                'project', 'category', 'subcategory', 'created_by', 'updated_by'
            ).get(id=scope_id)
        except MonthlyScopeWork.DoesNotExist:
            return None

        # Get daily progress breakdown
        daily_progress = DPRActivity.objects.filter(
            scope=scope,
            dpr__status__in=['approved', 'pending_pmc_head', 'pending_coordinator', 'pending_team_lead']
        ).select_related('dpr').order_by('date').values(
            'date', 'executed_quantity', 'cumulative_quantity',
            'progress_percentage', 'dpr__report_date'
        )

        # Get latest DPR update
        latest_dpr = DPRActivity.objects.filter(
            scope=scope
        ).select_related('dpr').order_by('-dpr__report_date').first()

        return {
            'scope': scope,
            'planned_quantity': scope.planned_quantity,
            'executed_quantity': scope.cumulative_quantity,
            'remaining_quantity': scope.remaining_quantity,
            'progress_percentage': scope.progress_percentage,
            'status': scope.status,
            'daily_progress': list(daily_progress),
            'latest_dpr_date': latest_dpr.dpr.report_date if latest_dpr else None,
            'total_dpr_entries': len(daily_progress)
        }