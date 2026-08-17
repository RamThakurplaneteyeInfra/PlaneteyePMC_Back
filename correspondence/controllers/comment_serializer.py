from collections.abc import Mapping

from rest_framework import serializers

from ..models.comment import CorrespondenceComment


COMMENT_MAX_LENGTH = 5000
EMPTY_COMMENT_MESSAGE = "Comment cannot be empty."


class CorrespondenceCommentSerializer(serializers.ModelSerializer):
    """Strict write serializer and compact read representation for comments."""

    comment = serializers.CharField(
        allow_blank=True,
        max_length=COMMENT_MAX_LENGTH,
        trim_whitespace=True,
    )
    commented_by = serializers.SerializerMethodField()

    class Meta:
        model = CorrespondenceComment
        fields = ["id", "comment", "commented_by", "created_at"]
        read_only_fields = ["id", "commented_by", "created_at"]

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = sorted(set(data.keys()) - {"comment"})
            if unknown_fields:
                raise serializers.ValidationError(
                    {
                        field: ["This field is not allowed."]
                        for field in unknown_fields
                    }
                )
        return super().to_internal_value(data)

    def validate_comment(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(EMPTY_COMMENT_MESSAGE)
        return value

    def get_commented_by(self, obj):
        user = obj.commented_by
        if user is None:
            return None
        return {
            "id": user.id,
            "name": user.get_full_name().strip() or user.get_username(),
        }
