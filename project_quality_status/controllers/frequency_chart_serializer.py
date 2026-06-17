"""Serializers for frequency chart register and frequency master."""

from rest_framework import serializers

from ..models.frequency_chart import FrequencyChartEntry, TestFrequencyMaster
from .frequency_chart_report import build_client_row, resolve_frequency_master


class TestFrequencyMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestFrequencyMaster
        fields = [
            "id",
            "projectName",
            "item_description",
            "type_of_test",
            "unit",
            "frequency_value",
            "frequency_quantity",
            "frequency_display",
            "is_archived",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "frequency_display", "created_at", "updated_at"]


class FrequencyChartEntrySerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField(read_only=True)
    client_row = serializers.SerializerMethodField(read_only=True)
    frequency_master_id = serializers.PrimaryKeyRelatedField(
        queryset=TestFrequencyMaster.objects.filter(is_archived=False),
        source="frequency_master",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = FrequencyChartEntry
        fields = [
            "id",
            "project_name",
            "projectName",
            "month",
            "year",
            "sr_no",
            "item_description",
            "type_of_test",
            "unit",
            "activity_name",
            "contractor_name",
            "frequency_master_id",
            "frequency_value",
            "frequency_quantity",
            "frequency_display",
            "qty_previous_bill",
            "qty_this_bill",
            "field_lab_previous_bill",
            "field_lab_this_bill",
            "third_party_previous_bill",
            "third_party_this_bill",
            "remarks",
            "is_archived",
            "client_row",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "project_name", "sr_no", "client_row", "created_at", "updated_at"]

    def get_project_name(self, obj) -> str:
        return obj.projectName

    def get_client_row(self, obj) -> dict:
        return build_client_row(obj)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "project_name" in data and "projectName" not in data:
            data["projectName"] = data["project_name"]
        if "activity" in data and "activity_name" not in data:
            data["activity_name"] = data["activity"]
        if "contractor" in data and "contractor_name" not in data:
            data["contractor_name"] = data["contractor"]

        return super().to_internal_value(data)

    def validate(self, attrs):
        project_name = (
            attrs.get("projectName")
            or (self.instance.projectName if self.instance else "")
        ).strip()
        if not project_name:
            raise serializers.ValidationError({"projectName": "project_name is required."})
        attrs["projectName"] = project_name
        return attrs

    def _apply_master_defaults(self, validated_data):
        master = validated_data.get("frequency_master")
        if master is None and validated_data.get("item_description") and validated_data.get("type_of_test"):
            master = resolve_frequency_master(
                validated_data["projectName"],
                validated_data["item_description"],
                validated_data["type_of_test"],
            )
            if master:
                validated_data["frequency_master"] = master

        if master:
            if validated_data.get("frequency_value") is None:
                validated_data["frequency_value"] = master.frequency_value
            if validated_data.get("frequency_quantity") is None:
                validated_data["frequency_quantity"] = master.frequency_quantity
            if not validated_data.get("frequency_display"):
                validated_data["frequency_display"] = master.frequency_display
            if not validated_data.get("unit"):
                validated_data["unit"] = master.unit

        return validated_data

    def create(self, validated_data):
        validated_data = self._apply_master_defaults(validated_data)
        validated_data["sr_no"] = FrequencyChartEntry.next_sr_no(
            validated_data["projectName"],
            validated_data["month"],
            validated_data["year"],
        )
        return FrequencyChartEntry.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data = self._apply_master_defaults(validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
