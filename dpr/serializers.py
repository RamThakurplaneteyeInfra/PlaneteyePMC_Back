from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import prefetch_related_objects
from rest_framework import serializers

from monthly_scope.models import MonthlyScopeWork
from monthly_scope.services import ScopeProgressService

from .models import DailyProgressReport, DPRActivity


class CachedScopePrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Resolve scope PKs from a request-level map to avoid per-activity lookups."""

    def to_internal_value(self, data):
        cache = self.context.get("_scope_by_id")
        if cache is not None:
            try:
                pk = int(data)
            except (TypeError, ValueError):
                self.fail("incorrect_type", data_type=type(data).__name__)
            obj = cache.get(pk)
            if obj is None:
                self.fail("does_not_exist", pk_value=data)
            return obj
        return super().to_internal_value(data)


def _load_scope_map(raw_activities) -> dict:
    if not isinstance(raw_activities, list):
        return {}
    ids = []
    for row in raw_activities:
        if not isinstance(row, dict) or row.get("scope") is None:
            continue
        try:
            ids.append(int(row.get("scope")))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    return {
        obj.pk: obj
        for obj in MonthlyScopeWork.objects.filter(pk__in=ids).select_related(
            "category", "subcategory"
        )
    }


def prime_dpr_for_serialization(dpr):
    """Prefetch nested activity/scope graph before serializer.data."""
    if dpr is None or not getattr(dpr, "pk", None):
        return dpr
    prefetch_related_objects(
        [dpr],
        "activities__scope__category",
        "activities__scope__subcategory",
        "submitted_by",
        "approved_by",
        "rejected_by",
    )
    return dpr


def _attach_recalculated_activities(dpr, activities, scope_map=None) -> None:
    """Reuse recalc rows for the response instead of a second activity prefetch."""
    if dpr is None or not getattr(dpr, "pk", None):
        return
    dpr_id = dpr.pk
    attached = [row for row in (activities or []) if getattr(row, "dpr_id", None) == dpr_id]
    if scope_map:
        for row in attached:
            cached = scope_map.get(row.scope_id)
            if cached is not None:
                row.scope = cached
    cache = getattr(dpr, "_prefetched_objects_cache", None)
    if cache is None:
        dpr._prefetched_objects_cache = {}
        cache = dpr._prefetched_objects_cache
    cache["activities"] = attached


def upsert_dpr_activities(dpr, activities_data, *, accumulate: bool) -> int:
    """
    Create or update activities for a DPR in bulk.

    accumulate=True matches POST /api/dpr/ append behavior (add quantities).
    accumulate=False matches submit replace-quantity behavior.
    """
    if not activities_data:
        return 0

    scope_ids = [
        activity_data["scope"].pk
        for activity_data in activities_data
        if activity_data.get("scope") is not None
    ]
    existing = {
        activity.scope_id: activity
        for activity in DPRActivity.objects.filter(dpr=dpr, scope_id__in=scope_ids)
    }
    to_create = []
    to_update = []
    added = 0
    for activity_data in activities_data:
        scope = activity_data.get("scope")
        if scope is None:
            continue
        current = existing.get(scope.pk)
        if current:
            new_qty = activity_data.get("executed_quantity", current.executed_quantity)
            if accumulate:
                current.executed_quantity += activity_data.get("executed_quantity", 0)
            else:
                current.executed_quantity = new_qty
            current.next_day_planned_work = activity_data.get(
                "next_day_planned_work", current.next_day_planned_work
            )
            current.remarks = activity_data.get("remarks", current.remarks)
            to_update.append(current)
        else:
            to_create.append(DPRActivity(dpr=dpr, **activity_data))
            added += 1
            existing[scope.pk] = to_create[-1]

    if to_update:
        DPRActivity.objects.bulk_update(
            to_update,
            ["executed_quantity", "next_day_planned_work", "remarks"],
        )
    if to_create:
        DPRActivity.objects.bulk_create(to_create)
    return added


class DPRActivitySerializer(serializers.ModelSerializer):
    """
    Serializer for DPR Activity (nested) with Monthly Scope integration
    """
    # Writable scope field - accepts PK from frontend (e.g. "scope": 8)
    scope = CachedScopePrimaryKeyField(
        queryset=MonthlyScopeWork.objects.all(),
        write_only=True,
        required=True
    )

    # Read-only display fields (kept for API responses)
    scope_id = serializers.SerializerMethodField(read_only=True)
    scope_name = serializers.SerializerMethodField(read_only=True)
    scope_description = serializers.SerializerMethodField(read_only=True)
    category_name = serializers.SerializerMethodField(read_only=True)
    subcategory_name = serializers.SerializerMethodField(read_only=True)
    unit = serializers.SerializerMethodField(read_only=True)
    planned_quantity = serializers.SerializerMethodField(read_only=True)
    section = serializers.SerializerMethodField(read_only=True)
    location = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DPRActivity
        fields = [
            'id',
            'scope',                    # Writable input field (must come before read-only scope_* fields)
            'scope_id',
            'scope_name',
            'scope_description',
            'category_name',
            'subcategory_name',
            'unit',
            'planned_quantity',
            'executed_quantity',
            'cumulative_quantity',
            'remaining_quantity',
            'progress_percentage',
            'section',
            'location',
            'status',
            'next_day_planned_work',
            'remarks'
        ]
        read_only_fields = ['cumulative_quantity', 'remaining_quantity', 'progress_percentage']

    def get_scope_id(self, obj):
        """Get scope ID"""
        return obj.scope.id if obj.scope else None

    def get_scope_name(self, obj):
        """Get scope name (using description or category-subcategory combo)"""
        if obj.scope:
            # Use description if available, otherwise category-subcategory
            if obj.scope.description:
                return obj.scope.description
            return f"{obj.scope.get_category_display_name()} - {obj.scope.get_subcategory_display_name()}"
        return None

    def get_scope_description(self, obj):
        """Get scope description"""
        return obj.scope.description if obj.scope else None

    def get_category_name(self, obj):
        """Get category name"""
        return obj.scope.get_category_display_name() if obj.scope else None

    def get_subcategory_name(self, obj):
        """Get subcategory name"""
        return obj.scope.get_subcategory_display_name() if obj.scope else None

    def get_unit(self, obj):
        """Get unit"""
        return obj.scope.unit if obj.scope else None

    def get_planned_quantity(self, obj):
        """Get planned quantity"""
        return obj.scope.planned_quantity if obj.scope else None

    def get_section(self, obj):
        """Get section"""
        return obj.scope.section if obj.scope else None

    def get_location(self, obj):
        """Get location"""
        return obj.scope.location if obj.scope else None

    def get_status(self, obj):
        """Get status"""
        return obj.scope.status if obj.scope else None

    def validate(self, data):
        """
        Custom validation for DPR Activity
        """
        scope = data.get('scope')
        executed_quantity = data.get('executed_quantity', 0)

        # Scope is now required
        if not scope:
            raise serializers.ValidationError({'scope': 'Scope is required'})

        # Executed quantity must be > 0
        if executed_quantity <= 0:
            raise serializers.ValidationError({
                'executed_quantity': 'Executed quantity must be greater than 0'
            })

        # Basic validation: executed quantity should not exceed planned quantity
        planned_quantity = scope.planned_quantity or Decimal('0.00')
        if executed_quantity > planned_quantity:
            raise serializers.ValidationError({
                'executed_quantity': f'Executed quantity ({executed_quantity}) cannot exceed planned quantity ({planned_quantity}) for this scope'
            })

        return data

    def create(self, validated_data):
        activity = super().create(validated_data)

        # Update progress calculations after creation (includes draft)
        from monthly_scope.services import ScopeProgressService
        ScopeProgressService.update_dpr_activity_progress(activity.id)
        activity.refresh_from_db()

        return activity

    def update(self, instance, validated_data):
        activity = super().update(instance, validated_data)

        # Update progress calculations after update
        from monthly_scope.services import ScopeProgressService
        ScopeProgressService.update_dpr_activity_progress(activity.id)
        activity.refresh_from_db()

        return activity




class DailyProgressReportSerializer(serializers.ModelSerializer):
    """
    Main serializer for Daily Progress Report
    Includes nested activities serializer
    """
    activities = DPRActivitySerializer(many=True, read_only=False, required=False)
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True, default=None)
    rejected_by_username = serializers.CharField(source='rejected_by.username', read_only=True, default=None)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    # Accept plain text or structured quality payload from the form
    quality_status = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = DailyProgressReport
        # drf-yasg: avoid OpenAPI schema name collisions with other serializers
        ref_name = "DPRDailyProgressReport"
        fields = [
            'id',
            'project_name',
            'job_no',
            'report_date',
            'unresolved_issues',
            'pending_letters',
            'quality_status',
            'next_day_incident',
            'bill_status',
            'gfc_status',
            'issued_by',
            'designation',
            'created_at',
            'updated_at',
            'activities',
            'status',
            'status_display',
            'submitted_by',
            'submitted_by_username',
            'current_approver_role',
            'rejection_reason',
            'rejected_by',
            'rejected_by_username',
            'approved_by',
            'approved_by_username',
            'approved_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'status', 'submitted_by', 'current_approver_role', 'rejection_reason', 'rejected_by', 'approved_by', 'approved_at']

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        # Frontend may send quality_status as an object (metrics card) — store as text
        quality = data.get("quality_status")
        if isinstance(quality, (dict, list)):
            import json
            data["quality_status"] = json.dumps(quality)

        if "_scope_by_id" not in self.context:
            self.context["_scope_by_id"] = _load_scope_map(data.get("activities"))

        return super().to_internal_value(data)

    def _extract_activities_data(self, validated_data):
        """
        Helper method to extract activities data from validated_data
        """
        return validated_data.pop('activities', [])





    def create(self, validated_data):
        """
        Override create to handle nested activities with smart DPR management:
        - Find existing DPR for same project/date/user, append activities
        - Or create new DPR if none exists
        """
        activities_data = self._extract_activities_data(validated_data)
        request = self.context.get('request')
        current_user = request.user if request else None

        try:
            with transaction.atomic():
                # Try to find existing DPR for same project, date, and user
                existing_dpr = None
                if current_user:
                    existing_dpr = DailyProgressReport.objects.filter(
                        project_name=validated_data.get('project_name'),
                        report_date=validated_data.get('report_date'),
                        created_by=current_user
                    ).first()

                if existing_dpr:
                    # Append activities to existing DPR
                    dpr = existing_dpr
                    activities_added = 0
                    previous_status = dpr.status

                    if activities_data:
                        activities_added = upsert_dpr_activities(
                            dpr, activities_data, accumulate=True
                        )

                    # Same-day FE "create" often hits this path. If the DPR is still
                    # draft/rejected, promote it to pending so email can fire without
                    # a separate /submit/ call (which is blocked once pending).
                    if dpr.status in (
                        DailyProgressReport.Status.DRAFT,
                        DailyProgressReport.Status.REJECTED,
                    ):
                        dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
                        dpr.submitted_by = current_user
                        dpr.current_approver_role = "Team Leader"
                        dpr.rejection_reason = ""
                        dpr.rejected_by = None
                        dpr.save(
                            update_fields=[
                                "status",
                                "submitted_by",
                                "current_approver_role",
                                "rejection_reason",
                                "rejected_by",
                                "updated_at",
                            ]
                        )
                        dpr._initial_submission = (
                            previous_status == DailyProgressReport.Status.DRAFT
                        )
                        dpr._resubmission = (
                            previous_status == DailyProgressReport.Status.REJECTED
                        )
                    elif dpr.status == DailyProgressReport.Status.PENDING_TEAM_LEAD:
                        # FE re-posted create for an already-pending same-day DPR.
                        # Re-queue submission email (dedupe prevents tight duplicates).
                        if not dpr.submitted_by_id and current_user:
                            dpr.submitted_by = current_user
                        dpr.current_approver_role = dpr.current_approver_role or "Team Leader"
                        dpr.save(update_fields=["submitted_by", "current_approver_role", "updated_at"])
                        dpr._resubmission = True
                    else:
                        dpr.save(update_fields=["updated_at"])

                    from monthly_scope.services import ScopeProgressService
                    rows = ScopeProgressService.recalculate_for_dpr(
                        dpr,
                        scope_ids=[
                            ad["scope"].pk
                            for ad in activities_data
                            if ad.get("scope") is not None
                        ] or None,
                        scopes_by_id=self.context.get("_scope_by_id") or None,
                    )
                    if hasattr(dpr, "_prefetched_objects_cache"):
                        dpr._prefetched_objects_cache = {}
                    _attach_recalculated_activities(
                        dpr, rows, self.context.get("_scope_by_id")
                    )

                    # Add custom response data
                    dpr._activities_added = activities_added
                    return dpr

                else:
                    # Create new DPR already in initial submission state so the
                    # FE does not need a follow-up /submit/ (which is draft/rejected only).
                    validated_data["created_by"] = current_user
                    validated_data["submitted_by"] = current_user
                    validated_data["status"] = DailyProgressReport.Status.PENDING_TEAM_LEAD
                    validated_data["current_approver_role"] = "Team Leader"
                    dpr = DailyProgressReport.objects.create(**validated_data)

                    if activities_data:
                        DPRActivity.objects.bulk_create(
                            [
                                DPRActivity(dpr=dpr, **activity_data)
                                for activity_data in activities_data
                            ]
                        )

                    from monthly_scope.services import ScopeProgressService
                    rows = ScopeProgressService.recalculate_for_dpr(
                        dpr,
                        scope_ids=[
                            ad["scope"].pk
                            for ad in activities_data
                            if ad.get("scope") is not None
                        ] or None,
                        scopes_by_id=self.context.get("_scope_by_id") or None,
                    )
                    if hasattr(dpr, "_prefetched_objects_cache"):
                        dpr._prefetched_objects_cache = {}
                    _attach_recalculated_activities(
                        dpr, rows, self.context.get("_scope_by_id")
                    )

                    # View uses this to queue the initial submission email once.
                    dpr._initial_submission = True
                    return dpr

        except IntegrityError:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                'non_field_errors': [
                    'A duplicate activity for the same scope already exists on this DPR.'
                ]
            })
        except serializers.ValidationError:
            raise
        except Exception:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                'non_field_errors': [
                    'Unexpected error while saving the DPR.'
                ]
            })

    def update(self, instance, validated_data):
        """
        Override update to handle nested activities with bulk creation and transaction
        """
        activities_data = self._extract_activities_data(validated_data)

        try:
            with transaction.atomic():
                # Update main DPR fields
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save()

                # Handle activities update
                if activities_data is not None:
                    # Delete existing activities and their progress impact
                    existing_activities = instance.activities.all()
                    scopes_to_update = set()
                    for activity in existing_activities:
                        if activity.scope:
                            scopes_to_update.add(activity.scope.id)
                    existing_activities.delete()

                    from monthly_scope.services import ScopeProgressService

                    # Bulk create new activities
                    if activities_data:
                        activities = [
                            DPRActivity(dpr=instance, **activity_data)
                            for activity_data in activities_data
                        ]
                        DPRActivity.objects.bulk_create(activities)

                    # Recalc scopes removed by delete + scopes on the new activities once.
                    for activity_data in activities_data or []:
                        scope = activity_data.get("scope")
                        if scope is not None:
                            scopes_to_update.add(scope.id)
                    rows = ScopeProgressService.recalculate_scopes(
                        scopes_to_update,
                        scopes_by_id=self.context.get("_scope_by_id") or None,
                    )
                    if hasattr(instance, "_prefetched_objects_cache"):
                        instance._prefetched_objects_cache = {}
                    _attach_recalculated_activities(
                        instance, rows, self.context.get("_scope_by_id")
                    )
                else:
                    if hasattr(instance, "_prefetched_objects_cache"):
                        instance._prefetched_objects_cache = {}
                    prime_dpr_for_serialization(instance)

                return instance
        except IntegrityError as e:
            # Handle unique constraint violations
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': ['Duplicate DPR for this project and date.']})
        except Exception as e:
            # Re-raise as ValidationError for better API response
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                'non_field_errors': [
                    'Unexpected error while saving the DPR.'
                ]
            }) from e
