from datetime import date

from rest_framework import serializers
from .models import ProjectProgressStatus


def _current_month_first_day() -> date:
    """Return the first day of the current month."""
    today = date.today()
    return date(today.year, today.month, 1)


class ProjectProgressStatusSerializer(serializers.ModelSerializer):
    """
    Serializer for Project Progress Status.
    
    Notes:
    - All percentage fields are validated to be between 0-100
    - progress_month is OPTIONAL — defaults to the first day of the current month
      when not provided by the frontend
    - progress_month should be the first day of the month (YYYY-MM-01)
    - One record per project per month (unique_together constraint)
    """
    
    progress_month_display = serializers.SerializerMethodField()
    # progress_month is optional — defaults to current month's first day
    progress_month = serializers.DateField(required=False, default=_current_month_first_day)
    monthly_plan = serializers.FloatField(required=False, default=0.0)
    cumulative_plan = serializers.FloatField(required=False, default=0.0)
    monthly_actual = serializers.FloatField(required=False, default=0.0)
    cumulative_actual = serializers.FloatField(required=False, default=0.0)
    created_by = serializers.CharField(required=False, default="Dashboard")
    
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
        - Ensure progress_month defaults to the first day of the current month
          when not provided by the frontend.
        - Ensure progress_month is always stored as the first day of the month.
        - Validate logical constraints (cumulative should generally be >= monthly)
        """
        # Default progress_month to current month's first day if not provided
        if not attrs.get("progress_month"):
            attrs["progress_month"] = _current_month_first_day()

        progress_month = attrs["progress_month"]
        # Normalise to first day of the month regardless of what was sent
        if progress_month.day != 1:
            attrs["progress_month"] = date(progress_month.year, progress_month.month, 1)
        
        # Set defaults for required fields if missing
        attrs.setdefault("cumulative_plan", attrs.get("monthly_plan", 0.0))
        attrs.setdefault("cumulative_actual", attrs.get("monthly_actual", 0.0))
        attrs.setdefault("created_by", "Dashboard")
        
        return attrs
    
    def create(self, validated_data):
        project_name = validated_data.pop("project_name")
        progress_month = validated_data.pop("progress_month")
        try:
            instance, created = ProjectProgressStatus.objects.update_or_create(
                project_name=project_name,
                progress_month=progress_month,
                defaults=validated_data
            )
            validated_data["project_name"] = project_name
            validated_data["progress_month"] = progress_month
            return instance
        except Exception as e:
            raise serializers.ValidationError({"detail": str(e)})
    
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
