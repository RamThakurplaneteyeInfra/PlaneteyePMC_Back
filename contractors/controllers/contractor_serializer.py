"""Contractor Master serializers."""

from rest_framework import serializers

from projects.models import Project

from ..models import Contractor


class ContractorSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField(read_only=True)
    contractor = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Contractor
        fields = [
            "id",
            "project_name",
            "contractor_name",
            "contractor_code",
            "contact_person",
            "email",
            "phone",
            "address",
            "status",
            "contractor",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "project_name", "contractor", "created_at", "updated_at"]

    def get_project_name(self, obj) -> str:
        return obj.project.name if obj.project_id else ""

    def get_contractor(self, obj) -> dict:
        return {"id": obj.id, "contractor_name": obj.contractor_name}

    def validate_contractor_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("contractor_name is required.")
        return value


class ContractorListSerializer(serializers.ModelSerializer):
    """Compact serializer for dropdown lists."""

    class Meta:
        model = Contractor
        fields = ["id", "contractor_name", "contractor_code", "status"]


class ContractorCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contractor
        fields = [
            "contractor_name",
            "contractor_code",
            "contact_person",
            "email",
            "phone",
            "address",
        ]

    def validate_contractor_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("contractor_name is required.")
        return value

    def validate(self, attrs):
        project = self.context.get("project")
        if project is None:
            raise serializers.ValidationError("Project context is required.")

        name = attrs.get("contractor_name", "")
        if Contractor.objects.filter(project=project, contractor_name__iexact=name).exists():
            raise serializers.ValidationError(
                {"contractor_name": f"A contractor named '{name}' already exists for this project."}
            )
        return attrs

    def create(self, validated_data):
        project = self.context["project"]
        return Contractor.objects.create(project=project, **validated_data)


class ContractorUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contractor
        fields = [
            "contractor_name",
            "contractor_code",
            "contact_person",
            "email",
            "phone",
            "address",
            "status",
        ]
        extra_kwargs = {
            "contractor_name": {"required": False},
            "status": {"required": False},
        }

    def validate_contractor_name(self, value: str) -> str:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise serializers.ValidationError("contractor_name cannot be blank.")
        return value

    def validate(self, attrs):
        instance = self.instance
        name = attrs.get("contractor_name")
        if name and instance:
            exists = (
                Contractor.objects.filter(
                    project=instance.project,
                    contractor_name__iexact=name,
                )
                .exclude(pk=instance.pk)
                .exists()
            )
            if exists:
                raise serializers.ValidationError(
                    {"contractor_name": f"A contractor named '{name}' already exists for this project."}
                )
        return attrs
