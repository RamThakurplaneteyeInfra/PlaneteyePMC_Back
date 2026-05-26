from django.db import transaction, IntegrityError
from rest_framework import serializers
from .models import DailyProgressReport, DPRActivity
from django.contrib.auth import get_user_model
from monthly_scope.services import ScopeProgressService
from monthly_scope.models import MonthlyScopeWork
from decimal import Decimal


class DPRActivitySerializer(serializers.ModelSerializer):
    """
    Serializer for DPR Activity (nested) with Monthly Scope integration
    """
    # Writable scope field - accepts PK from frontend (e.g. "scope": 8)
    scope = serializers.PrimaryKeyRelatedField(
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

        # Update progress calculations after creation
        from monthly_scope.services import ScopeProgressService
        ScopeProgressService.update_dpr_activity_progress(activity.id)

        return activity

    def update(self, instance, validated_data):
        activity = super().update(instance, validated_data)

        # Update progress calculations after update
        from monthly_scope.services import ScopeProgressService
        ScopeProgressService.update_dpr_activity_progress(activity.id)

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

                    if activities_data:
                        for activity_data in activities_data:
                            scope = activity_data.get('scope')
                            if scope:
                                # Check if activity for this scope already exists
                                existing_activity = DPRActivity.objects.filter(
                                    dpr=dpr, scope=scope
                                ).first()

                                if existing_activity:
                                    # Update existing activity quantities
                                    existing_activity.executed_quantity += activity_data.get('executed_quantity', 0)
                                    existing_activity.next_day_planned_work = activity_data.get('next_day_planned_work', '')
                                    existing_activity.remarks = activity_data.get('remarks', '')
                                    existing_activity.save()
                                    activity_id = existing_activity.id
                                else:
                                    # Create new activity
                                    activity = DPRActivity(dpr=dpr, **activity_data)
                                    activity.save()
                                    activities_added += 1
                                    activity_id = activity.id

                                # Update progress for this scope
                                from monthly_scope.services import ScopeProgressService
                                ScopeProgressService.update_dpr_activity_progress(activity_id)

                    # Update DPR timestamp
                    dpr.save(update_fields=['updated_at'])

                    # Add custom response data
                    dpr._activities_added = activities_added
                    return dpr

                else:
                    # Create new DPR
                    validated_data['created_by'] = current_user
                    dpr = DailyProgressReport.objects.create(**validated_data)

                    # Create associated activities with progress updates
                    if activities_data:
                        for activity_data in activities_data:
                            activity = DPRActivity(dpr=dpr, **activity_data)
                            activity.save()

                            # Update progress for this scope
                            from monthly_scope.services import ScopeProgressService
                            ScopeProgressService.update_dpr_activity_progress(activity.id)

                    return dpr

        except Exception as e:
            # Re-raise as ValidationError for better API response
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': [str(e)]})

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

                    # Update progress for affected scopes
                    from monthly_scope.services import ScopeProgressService
                    for scope_id in scopes_to_update:
                        ScopeProgressService.update_scope_progress(scope_id)

                    # Bulk create new activities
                    if activities_data:
                        activities = []
                        for activity_data in activities_data:
                            activity = DPRActivity(dpr=instance, **activity_data)
                            activities.append(activity)

                        DPRActivity.objects.bulk_create(activities)

                        # Update progress for new activities
                        for activity_data in activities_data:
                            if 'scope' in activity_data:
                                scope = activity_data['scope']
                                created_activity = DPRActivity.objects.filter(
                                    dpr=instance, scope=scope
                                ).first()
                                if created_activity:
                                    ScopeProgressService.update_dpr_activity_progress(created_activity.id)

                return instance
        except IntegrityError as e:
            # Handle unique constraint violations
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': ['Duplicate DPR for this project and date.']})
        except Exception as e:
            # Re-raise as ValidationError for better API response
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': [str(e)]})
