from django.db import transaction, IntegrityError
from rest_framework import serializers

from .models import MachineryMaster, MachineryItem, PlantMachineryReport


class MachineryMasterSerializer(serializers.ModelSerializer):
    """Serializer for global machinery catalogue."""

    class Meta:
        model = MachineryMaster
        fields = [
            "id",
            "name",
            "unit",
            "category",
            "is_default",
            "created_at",
        ]
        read_only_fields = ["id", "is_default", "created_at"]

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("name cannot be blank.")

        qs = MachineryMaster.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Machinery with this name already exists."
            )
        return value

    def validate_unit(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("unit cannot be blank.")
        return value


class MachineryItemSerializer(serializers.ModelSerializer):
    """
    Log line item — references machinery_master.
    Legacy fields particular / unit are read-only aliases from master.
    """

    machinery_master_id = serializers.PrimaryKeyRelatedField(
        queryset=MachineryMaster.objects.all(),
        source="machinery_master",
        write_only=True,
    )
    machinery_master = MachineryMasterSerializer(read_only=True)
    particular = serializers.CharField(source="machinery_master.name", read_only=True)
    unit = serializers.CharField(source="machinery_master.unit", read_only=True)
    category = serializers.CharField(source="machinery_master.category", read_only=True)

    class Meta:
        model = MachineryItem
        fields = [
            "id",
            "machinery_master_id",
            "machinery_master",
            "particular",
            "unit",
            "category",
            "sr_no",
            "qty",
            "remark",
            "status",
            "last_updated",
        ]
        read_only_fields = ["id", "last_updated"]

    def validate_qty(self, value):
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative.")
        return value

    def validate_status(self, value):
        valid_statuses = [choice[0] for choice in MachineryItem.STATUS_CHOICES]
        if value not in valid_statuses:
            raise serializers.ValidationError(
                f"Status must be one of: {', '.join(valid_statuses)}"
            )
        return value

    def validate(self, attrs):
        report = attrs.get("report") or getattr(self.instance, "report", None)
        machinery_master = attrs.get("machinery_master") or getattr(
            self.instance, "machinery_master", None
        )
        if report and machinery_master:
            qs = MachineryItem.objects.filter(
                report=report, machinery_master=machinery_master
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "machinery_master_id": (
                            "This machinery is already logged on this report."
                        )
                    }
                )
        return attrs

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        for alias in ("machinery_id", "master_id", "machinery_master"):
            if alias in data and "machinery_master_id" not in data:
                if alias == "machinery_master" and isinstance(data[alias], dict):
                    data["machinery_master_id"] = data[alias].get("id")
                elif alias != "machinery_master":
                    data["machinery_master_id"] = data[alias]

        # Legacy: resolve particular name to machinery_master_id
        if "machinery_master_id" not in data and "particular" in data:
            name = str(data.get("particular", "")).strip()
            if name:
                master = MachineryMaster.objects.filter(name__iexact=name).first()
                if master:
                    data["machinery_master_id"] = master.pk
                else:
                    raise serializers.ValidationError(
                        {
                            "particular": (
                                f"No machinery master found for '{name}'. "
                                "Add it via /api/machinery-master/ first."
                            )
                        }
                    )

        return super().to_internal_value(data)


class PlantMachineryReportSerializer(serializers.ModelSerializer):
    machinery_items = MachineryItemSerializer(many=True, required=False)

    @staticmethod
    def _dedupe_machinery_items(items_data: list) -> list:
        """
        One row per machinery_master per report.
        If the client sends duplicates, merge qty and keep the first sr_no/remark/status.
        """
        if not items_data:
            return items_data

        merged: dict = {}
        order: list = []
        for item in items_data:
            master = item.get("machinery_master")
            if master is None:
                continue
            mid = master.pk
            if mid not in merged:
                merged[mid] = dict(item)
                order.append(mid)
                continue
            existing = merged[mid]
            existing["qty"] = int(existing.get("qty") or 0) + int(item.get("qty") or 0)
            if item.get("remark") and not existing.get("remark"):
                existing["remark"] = item.get("remark")
            if item.get("status"):
                existing["status"] = item.get("status")

        return [merged[mid] for mid in order]

    class Meta:
        model = PlantMachineryReport
        fields = [
            "id",
            "project_name",
            "report_date",
            "created_by",
            "created_at",
            "updated_at",
            "machinery_items",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        project_name = (attrs.get("project_name") or "").strip()
        report_date = attrs.get("report_date")

        if not project_name:
            raise serializers.ValidationError(
                {"project_name": "This field may not be blank."}
            )

        instance = getattr(self, "instance", None)
        upsert_target = self.context.get("upsert_report")
        if upsert_target is not None:
            return attrs

        if not instance or (
            instance.project_name != project_name
            or instance.report_date != report_date
        ):
            if PlantMachineryReport.objects.filter(
                project_name=project_name, report_date=report_date
            ).exists():
                raise serializers.ValidationError(
                    "A report for this project and date already exists. "
                    "Use POST again to update (upsert) or PATCH the existing report."
                )
        return attrs

    def validate_machinery_items(self, value):
        if not value:
            return value
        return self._dedupe_machinery_items(value)

    def create(self, validated_data):
        items_data = self._dedupe_machinery_items(
            validated_data.pop("machinery_items", [])
        )

        upsert = self.context.get("upsert_report")
        if upsert is not None:
            validated_data["machinery_items"] = items_data
            return self.update(upsert, validated_data)

        try:
            with transaction.atomic():
                report = PlantMachineryReport.objects.create(**validated_data)
                for item_data in items_data:
                    MachineryItem.objects.create(report=report, **item_data)
                return report
        except IntegrityError as exc:
            raise serializers.ValidationError(
                self._integrity_message(exc)
            )

    def update(self, instance, validated_data):
        items_data = validated_data.pop("machinery_items", None)
        if items_data is not None:
            items_data = self._dedupe_machinery_items(items_data)

        try:
            with transaction.atomic():
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save()

                if items_data is not None:
                    instance.machinery_items.all().delete()
                    for item_data in items_data:
                        MachineryItem.objects.create(report=instance, **item_data)

                return instance
        except IntegrityError as exc:
            raise serializers.ValidationError(
                self._integrity_message(exc)
            )

    @staticmethod
    def _integrity_message(exc: IntegrityError) -> str:
        msg = str(exc)
        if "pm_unique_report_machinery_master" in msg:
            return "Duplicate machinery on this report is not allowed."
        return "A report for this project and date already exists."
