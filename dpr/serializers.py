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

    def validate_target_achieved(self, value):
        """
        Validate that target_achieved is between 0 and 100
        This is also handled at model level, but adding here for API clarity
        """
        if value < 0 or value > 100:
            raise serializers.ValidationError("Target achieved must be between 0 and 100.")
        return value


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
    
    def validate(self, attrs):
        """
        Additional validation for the entire DPR object
        """
        # Validate activities if present
        if 'activities' in attrs and attrs['activities']:
            for idx, activity in enumerate(attrs['activities']):
                # Validate required fields in activities
                if 'date' not in activity or not activity['date']:
                    raise serializers.ValidationError({
                        'activities': {idx: {'date': 'Date is required for each activity.'}}
                    })
                if 'activity' not in activity or not activity['activity']:
                    raise serializers.ValidationError({
                        'activities': {idx: {'activity': 'Activity description is required.'}}
                    })
                # target_achieved is validated by DPRActivitySerializer
        
        return attrs

    def create(self, validated_data):
        """
        Override create to handle nested activities
        """
        activities_data = validated_data.pop('activities', [])
        
        try:
            dpr = DailyProgressReport.objects.create(**validated_data)
            
            # Create associated activities
            for activity_data in activities_data:
                DPRActivity.objects.create(dpr=dpr, **activity_data)
            
            return dpr
        except Exception as e:
            # Re-raise as ValidationError for better API response
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'non_field_errors': [str(e)]})

    def update(self, instance, validated_data):
        """
        Override update to handle nested activities
        """
        activities_data = validated_data.pop('activities', None)
        
        # Update main DPR fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle activities update
        if activities_data is not None:
            # Delete existing activities
            instance.activities.all().delete()
            # Create new activities
            for activity_data in activities_data:
                DPRActivity.objects.create(dpr=instance, **activity_data)
        
        return instance
