"""
PO-31 Reminders API.

GET    /api/reminders/
POST   /api/reminders/
GET    /api/reminders/{id}/
PATCH  /api/reminders/{id}/
PUT    /api/reminders/{id}/
DELETE /api/reminders/{id}/
POST   /api/reminders/{id}/complete/
POST   /api/reminders/{id}/dismiss/
POST   /api/reminders/{id}/snooze/
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from accounts.rbac_checks import assert_project_writable

from .filters import ReminderFilter
from .models import Reminder
from .serializers import ReminderSerializer, ReminderSnoozeSerializer


class ReminderViewSet(viewsets.ModelViewSet):
    serializer_class = ReminderSerializer
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.GENERAL
    filterset_class = ReminderFilter
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            Reminder.objects.select_related(
                "project",
                "assigned_to",
                "created_by",
            )
            .all()
            .order_by("due_at", "-created_at")
        )
        return filter_queryset_by_project_access(qs, self.request.user, "project")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "success": True,
                "message": "Reminder created successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        assert_project_writable(instance.project)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {
                "success": True,
                "message": "Reminder updated successfully.",
                "data": serializer.data,
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        assert_project_writable(instance.project)
        self.perform_destroy(instance)
        return Response(
            {
                "success": True,
                "message": "Reminder deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    def _action_response(self, reminder: Reminder, message: str):
        data = ReminderSerializer(reminder, context={"request": self.request}).data
        return Response({"success": True, "message": message, "data": data})

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        reminder = self.get_object()
        assert_project_writable(reminder.project)
        if reminder.status == Reminder.STATUS_COMPLETED:
            return Response(
                {
                    "success": False,
                    "message": "Reminder is already completed.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        reminder.mark_completed(actor=request.user)
        return self._action_response(reminder, "Reminder marked as completed.")

    @action(detail=True, methods=["post"], url_path="dismiss")
    def dismiss(self, request, pk=None):
        reminder = self.get_object()
        assert_project_writable(reminder.project)
        if reminder.status == Reminder.STATUS_DISMISSED:
            return Response(
                {
                    "success": False,
                    "message": "Reminder is already dismissed.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        reminder.mark_dismissed(actor=request.user)
        return self._action_response(reminder, "Reminder dismissed.")

    @action(detail=True, methods=["post"], url_path="snooze")
    def snooze(self, request, pk=None):
        reminder = self.get_object()
        assert_project_writable(reminder.project)
        serializer = ReminderSnoozeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reminder.snooze(until=serializer.validated_data["snooze_until"])
        except DjangoValidationError as exc:
            return Response(
                {"success": False, "message": "Invalid snooze request.", "errors": exc.message_dict},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._action_response(reminder, "Reminder snoozed.")
