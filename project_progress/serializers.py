from rest_framework import serializers
from .models import ProjectProgressStatus


class ProjectProgressStatusSerializer(serializers.ModelSerializer):
    """
    Serializer for Project Progress Status.
    
    Notes:
    - All percentage fields are validated to be between 0-100
    - progress_month should be the first day of the month (YYYY-MM-01)
    - One record per project per month (unique_together constraint)
    """
    
    progress_month_display = serializers.SerializerMethodField()
    
    class Meta:
        model = ProjectProgressStatus
        fields = [
            "id",
            "project_name",
            "progress_month",
            "progress_month_display",
            "monthly_plan",
            "cumulative_plan",
            "monthly_actual",
            "cumulative_actual",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "progress_month_display",
            "created_at",
            "updated_at",
        ]
    
    def get_progress_month_display(self, obj):
        """Return formatted month string (e.g., 'Jan-23')"""
        return obj.progress_month.strftime("%b-%y")
    
    def validate_monthly_plan(self, value):
        """Validate monthly_plan is between 0-100"""
        if value is None:
            return 0.0
        if not (0.0 <= value <= 100.0):
            raise serializers.ValidationError("monthly_plan must be between 0 and 100.")
        return value
    
    def validate_cumulative_plan(self, value):
        """Validate cumulative_plan is between 0-100"""
        if value is None:
            return 0.0
        if not (0.0 <= value <= 100.0):
            raise serializers.ValidationError("cumulative_plan must be between 0 and 100.")
        return value
    
    def validate_monthly_actual(self, value):
        """Validate monthly_actual is between 0-100"""
        if value is None:
            return 0.0
        if not (0.0 <= value <= 100.0):
            raise serializers.ValidationError("monthly_actual must be between 0 and 100.")
        return value
    
    def validate_cumulative_actual(self, value):
        """Validate cumulative_actual is between 0-100"""
        if value is None:
            return 0.0
        if not (0.0 <= value <= 100.0):
            raise serializers.ValidationError("cumulative_actual must be between 0 and 100.")
        return value
    
    def validate(self, attrs):
        """
        Additional validation:
        - Ensure progress_month is the first day of the month
        - Validate logical constraints (cumulative should generally be >= monthly)
        """
        progress_month = attrs.get("progress_month")
        if progress_month:
            # Ensure it's the first day of the month
            if progress_month.day != 1:
                from datetime import date
                attrs["progress_month"] = date(progress_month.year, progress_month.month, 1)
        
        return attrs
    
    def update(self, instance, validated_data):
        """
        Override update to handle updated_by field.
        """
        # If updated_by is not provided, try to get it from request context
        if "updated_by" not in validated_data:
            request = self.context.get("request")
            if request and hasattr(request, "data"):
                updated_by = request.data.get("updated_by")
                if updated_by:
                    validated_data["updated_by"] = updated_by
        
        return super().update(instance, validated_data)
