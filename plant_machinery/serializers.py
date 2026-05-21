from django.db import transaction, IntegrityError
from rest_framework import serializers
from .models import PlantMachineryReport, MachineryItem


class MachineryItemSerializer(serializers.ModelSerializer):
    """
    Serializer for individual machinery / equipment items.
    Used both nested inside reports and for standalone /items/ endpoints.
    """

    class Meta:
        model = MachineryItem
        fields = [
            'id',
            'sr_no',
            'particular',
            'unit',
            'qty',
            'remark',
            'status',
            'last_updated',
        ]
        read_only_fields = ['id', 'last_updated']

    def validate_qty(self, value):
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative.")
        return value

    def validate_status(self, value):
        valid_statuses = [choice[0] for choice in MachineryItem.STATUS_CHOICES]
        if value not in valid_statuses:
            raise serializers.ValidationError(f"Status must be one of: {', '.join(valid_statuses)}")
        return value


class PlantMachineryReportSerializer(serializers.ModelSerializer):
    """
    Main serializer for Plant & Machinery reports.
    Supports nested creation and update of machinery_items.
    """

    machinery_items = MachineryItemSerializer(many=True, required=False)

    class Meta:
        model = PlantMachineryReport
        fields = [
            'id',
            'project_name',
            'report_date',
            'created_by',
            'created_at',
            'updated_at',
            'machinery_items',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        """
        Additional validation: duplicate (project_name, report_date) handled by DB unique_together,
        but we give a friendly error message on create/update.
        """
        project_name = (attrs.get('project_name') or '').strip()
        report_date = attrs.get('report_date')

        if not project_name:
            raise serializers.ValidationError({"project_name": "This field may not be blank."})

        # Check for duplicate only on create or when changing keys
        instance = getattr(self, 'instance', None)
        if not instance or (instance.project_name != project_name or instance.report_date != report_date):
            if PlantMachineryReport.objects.filter(
                project_name=project_name, report_date=report_date
            ).exists():
                raise serializers.ValidationError(
                    "A report for this project and date already exists. "
                    "Each project can have only one report per date."
                )
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop('machinery_items', [])

        try:
            with transaction.atomic():
                report = PlantMachineryReport.objects.create(**validated_data)

                for item_data in items_data:
                    MachineryItem.objects.create(report=report, **item_data)

                return report
        except IntegrityError:
            raise serializers.ValidationError(
                "A report for this project and date already exists."
            )

    def update(self, instance, validated_data):
        items_data = validated_data.pop('machinery_items', None)

        try:
            with transaction.atomic():
                # Update simple fields
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save()

                if items_data is not None:
                    # Replace all items (common pattern for this kind of inventory form)
                    instance.machinery_items.all().delete()
                    for item_data in items_data:
                        MachineryItem.objects.create(report=instance, **item_data)

                return instance
        except IntegrityError:
            raise serializers.ValidationError(
                "A report for this project and date already exists."
            )
