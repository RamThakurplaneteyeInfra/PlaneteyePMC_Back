from rest_framework import serializers

from .models import OrganizationRegistration
from .storage import maybe_upload_logo_to_s3, validate_logo


def _required_trimmed(value, message):
    text = (value or "").strip() if isinstance(value, str) else value
    if not text:
        raise serializers.ValidationError(message)
    return text


class OrganizationRegistrationSerializer(serializers.ModelSerializer):
    logo = serializers.FileField(write_only=True, required=True, allow_empty_file=False)
    logo_url = serializers.SerializerMethodField(read_only=True)

    official_email = serializers.EmailField(
        required=True,
        error_messages={
            "required": "Official email is required.",
            "blank": "Official email is required.",
            "invalid": "Enter a valid official email.",
        },
    )
    admin_email = serializers.EmailField(
        required=True,
        error_messages={
            "required": "Admin email is required.",
            "blank": "Admin email is required.",
            "invalid": "Enter a valid admin email.",
        },
    )

    class Meta:
        model = OrganizationRegistration
        fields = [
            "id",
            "legal_name",
            "display_name",
            "office_address",
            "city",
            "pin",
            "phone",
            "official_email",
            "admin_name",
            "admin_email",
            "logo",
            "logo_url",
            "status",
            "submitted_at",
        ]
        read_only_fields = ["id", "status", "submitted_at", "logo_url"]
        extra_kwargs = {
            "legal_name": {"error_messages": {"required": "Organization legal name is required.", "blank": "Organization legal name is required."}},
            "display_name": {"error_messages": {"required": "Display name is required.", "blank": "Display name is required."}},
            "office_address": {"error_messages": {"required": "Registered office address is required.", "blank": "Registered office address is required."}},
            "city": {"error_messages": {"required": "City is required.", "blank": "City is required."}},
            "pin": {"error_messages": {"required": "PIN / postal code is required.", "blank": "PIN / postal code is required."}},
            "phone": {"error_messages": {"required": "Phone is required.", "blank": "Phone is required."}},
            "admin_name": {"error_messages": {"required": "Admin name is required.", "blank": "Admin name is required."}},
            "logo": {"error_messages": {"required": "Organization logo is required.", "empty": "Please upload a non-empty logo file."}},
        }

    def get_logo_url(self, obj):
        return obj.logo_public_url(self.context.get("request"))

    def validate_legal_name(self, value):
        return _required_trimmed(value, "Organization legal name is required.")

    def validate_display_name(self, value):
        return _required_trimmed(value, "Display name is required.")

    def validate_office_address(self, value):
        return _required_trimmed(value, "Registered office address is required.")

    def validate_city(self, value):
        return _required_trimmed(value, "City is required.")

    def validate_pin(self, value):
        return _required_trimmed(value, "PIN / postal code is required.")

    def validate_phone(self, value):
        return _required_trimmed(value, "Phone is required.")

    def validate_admin_name(self, value):
        return _required_trimmed(value, "Admin name is required.")

    def validate_official_email(self, value):
        return _required_trimmed(value, "Official email is required.").lower()

    def validate_admin_email(self, value):
        return _required_trimmed(value, "Admin email is required.").lower()

    def validate_logo(self, value):
        filename, _content_type = validate_logo(value)
        self.context["logo_original_name"] = filename
        return value

    def create(self, validated_data):
        original_name = self.context.get("logo_original_name") or getattr(
            validated_data.get("logo"), "name", ""
        )
        instance = OrganizationRegistration.objects.create(
            logo_original_name=original_name,
            status=OrganizationRegistration.STATUS_PENDING,
            **validated_data,
        )
        maybe_upload_logo_to_s3(instance)
        return instance
