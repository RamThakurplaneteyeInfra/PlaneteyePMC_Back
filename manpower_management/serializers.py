from django.db import IntegrityError
from rest_framework import serializers
from .models import ManpowerRecord


class ManpowerRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for ManpowerRecord.
    - difference is auto-calculated in the model
    - Includes validations for negative values and uniqueness
    """

    class Meta:
        model = ManpowerRecord
        fields = [
            'id',
            'project_name',
            'month',
            'year',
            'monthly_planned_manpower',
            'actual_manpower',
            'difference',
            'remarks',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'difference', 'created_at', 'updated_at']

    def validate_monthly_planned_manpower(self, value):
        if value < 0:
            raise serializers.ValidationError("Monthly planned manpower cannot be negative.")
        return value

    def validate_actual_manpower(self, value):
        if value < 0:
            raise serializers.ValidationError("Actual manpower cannot be negative.")
        return value

    def validate(self, attrs):
        """
        Check for duplicate (project_name + month + year)
        """
        project_name = (attrs.get('project_name') or '').strip()
        month = attrs.get('month')
        year = attrs.get('year')

        instance = getattr(self, 'instance', None)

        # Only check uniqueness if creating or changing the unique fields
        if not instance or (
            instance.project_name != project_name or
            instance.month != month or
            instance.year != year
        ):
            if ManpowerRecord.objects.filter(
                project_name=project_name,
                month=month,
                year=year
            ).exists():
                raise serializers.ValidationError(
                    "A manpower record for this project, month, and year already exists."
                )
        return attrs

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                "A manpower record for this project, month, and year already exists."
            )
