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

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access, user_has_project_access
from accounts.rbac_checks import assert_project_writable
from projects.models import Project

from .filters import ReminderFilter
from .models import Reminder
from .serializers import ReminderSerializer, ReminderSnoozeSerializer

User = get_user_model()


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

    @action(detail=False, methods=["get"], url_path="assignees")
    def assignees(self, request):
        """
        Active auth users who can be reminder assignees for a project.

        GET /api/reminders/assignees/?project_id=101

        Prefer this over /available-users/ (that endpoint is for *unassigned*
        staffing and wrongly excludes people already on the project).
        """
        project_id = request.query_params.get("project_id")
        if not project_id:
            return Response(
                {
                    "success": False,
                    "message": "Query parameter project_id is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            return Response(
                {"success": False, "message": "project_id must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            return Response(
                {"success": False, "message": f"Project id {project_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not user_has_project_access(request.user, project):
            return Response(
                {"success": False, "message": "You do not have access to this project."},
                status=status.HTTP_403_FORBIDDEN,
            )

        ids = set()
        for attr in (
            "pmc_head_id",
            "team_lead_id",
            "site_engineer_id",
            "billing_site_engineer_id",
            "qaqc_site_engineer_id",
            "hse_site_engineer_id",
            "created_by_id",
        ):
            uid = getattr(project, attr, None)
            if uid:
                ids.add(uid)
        ids.update(project.site_engineers.values_list("id", flat=True))
        ids.update(project.coordinators.values_list("id", flat=True))
        if hasattr(project, "assigned_users"):
            ids.update(project.assigned_users.values_list("id", flat=True))

        users = (
            User.objects.filter(id__in=ids, is_active=True)
            .prefetch_related("groups")
            .order_by("first_name", "username")
        )
        data = []
        for u in users:
            role = u.groups.values_list("name", flat=True).first() or ""
            full = f"{u.first_name or ''} {u.last_name or ''}".strip()
            data.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "name": full or u.username,
                    "full_name": full or u.username,
                    "email": u.email or "",
                    "role": role,
                }
            )
        return Response({"success": True, "count": len(data), "data": data})

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
