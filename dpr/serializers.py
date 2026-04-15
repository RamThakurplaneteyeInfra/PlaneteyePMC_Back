from django.db import transaction, IntegrityError
from rest_framework import serializers
from .models import DailyProgressReport, DPRActivity
from django.contrib.auth import get_user_model


class DPRActivitySerializer(serializers.ModelSerializer):
    """
    Serializer for DPR Activity (nested)
    """
    class Meta:
        model = DPRActivity
        fields = [
            'id',
            'date',
            'activity',
            'deliverables',
            'target_achieved',
            'next_day_plan',
            'remarks'
        ]




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
        read_only_fields = ['id', 'created_at', 'updated_at', 'status', 'submitted_by', 'current_approver_role', 'rejection_reason', 'rejected_by', 'approved_by', 'approved_at']

    def _extract_activities_data(self, validated_data):
        """
        Helper method to extract activities data from validated_data
        """
        return validated_data.pop('activities', [])





    def create(self, validated_data):
        """
        Override create to handle nested activities with bulk creation and transaction
        """
        activities_data = self._extract_activities_data(validated_data)

        try:
            with transaction.atomic():
                dpr = DailyProgressReport.objects.create(**validated_data)

                # Bulk create associated activities
                if activities_data:
                    activities = [DPRActivity(dpr=dpr, **activity_data) for activity_data in activities_data]
                    DPRActivity.objects.bulk_create(activities)

                return dpr
        except IntegrityError as e:
            # Handle unique constraint violations
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': ['Duplicate DPR for this project and date.']})
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
                    # Delete existing activities
                    instance.activities.all().delete()
                    # Bulk create new activities
                    if activities_data:
                        activities = [DPRActivity(dpr=instance, **activity_data) for activity_data in activities_data]
                        DPRActivity.objects.bulk_create(activities)

                return instance
        except IntegrityError as e:
            # Handle unique constraint violations
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': ['Duplicate DPR for this project and date.']})
        except Exception as e:
            # Re-raise as ValidationError for better API response
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': [str(e)]})
