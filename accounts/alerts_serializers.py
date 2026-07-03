"""Serializers for in-app alerts (accounts.Notification)."""

from rest_framework import serializers

from .models import Notification


class AlertSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField()
    sender = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "module_name",
            "project_name",
            "action_type",
            "notification_type",
            "sender",
            "created_at",
            "is_read",
        ]
        read_only_fields = fields

    def get_project_name(self, obj):
        if obj.project_id:
            return obj.project.name
        return None

    def get_sender(self, obj):
        if not obj.sender_id:
            return None
        return obj.sender.get_full_name() or obj.sender.username


class AlertReadStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["is_read"]
