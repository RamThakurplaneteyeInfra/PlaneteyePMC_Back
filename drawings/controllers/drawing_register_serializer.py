"""Serializers for drawing register items, workflow events, and file attachments."""

from rest_framework import serializers

from projects.models import Project

from ..models.drawing_file import DrawingFile
from ..models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent
from .drawing_report import build_client_row


class DrawingFileSerializer(serializers.ModelSerializer):
    file_url = serializers.URLField(read_only=True)

    class Meta:
        model = DrawingFile
        fields = [
            "id",
            "original_filename",
            "revision",
            "file_size",
            "content_type",
            "file_url",
            "created_at",
        ]
        read_only_fields = fields


class DrawingWorkflowEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DrawingWorkflowEvent
        fields = ["id", "action", "event_date", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]


class DrawingRegisterItemSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField(read_only=True)
    workflow_events = DrawingWorkflowEventSerializer(many=True, required=False)
    client_row = serializers.SerializerMethodField(read_only=True)
    drawings = DrawingFileSerializer(source="active_files", many=True, read_only=True)

    class Meta:
        model = DrawingRegisterItem
        fields = [
            "id",
            "project_name",
            "sr_no",
            "drawing_name",
            "contractor_name",
            "revision",
            "remarks",
            "submitted_date",
            "consultant_comments_date",
            "resubmitted_date",
            "approved_date",
            "workflow_events",
            "drawings",
            "client_row",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "sr_no",
            "client_row",
            "drawings",
            "created_at",
            "updated_at",
        ]

    def get_project_name(self, obj) -> str:
        return obj.project_name

    def get_client_row(self, obj) -> dict:
        return build_client_row(obj)

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "projectName" in data and "project_name" not in data:
            data["project_name"] = data["projectName"]
        if "design_and_drawing" in data and "drawing_name" not in data:
            data["drawing_name"] = data["design_and_drawing"]

        ret = super().to_internal_value(data)
        ret["_project_name"] = str(data.get("project_name", "")).strip()
        return ret

    def validate(self, attrs):
        project_name = attrs.pop("_project_name", "").strip()
        instance = self.instance

        if project_name:
            try:
                attrs["project"] = Project.objects.get(name__iexact=project_name)
            except Project.DoesNotExist:
                raise serializers.ValidationError(
                    {"project_name": f"No project found with name '{project_name}'."}
                )
        elif instance is not None:
            attrs["project"] = instance.project
        else:
            raise serializers.ValidationError({"project_name": "project_name is required."})

        return attrs

    def create(self, validated_data):
        events_data = validated_data.pop("workflow_events", [])
        project = validated_data["project"]
        validated_data["sr_no"] = DrawingRegisterItem.next_sr_no(project.id)
        item = DrawingRegisterItem.objects.create(**validated_data)
        self._sync_events(item, events_data)
        return item

    def update(self, instance, validated_data):
        events_data = validated_data.pop("workflow_events", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if events_data is not None:
            instance.workflow_events.all().delete()
            self._sync_events(instance, events_data)
        return instance

    @staticmethod
    def _sync_events(item: DrawingRegisterItem, events_data: list[dict]):
        for event in events_data:
            DrawingWorkflowEvent.objects.create(drawing=item, **event)
