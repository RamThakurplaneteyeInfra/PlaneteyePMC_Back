import logging

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.rbac import filter_queryset_by_project_access
from services.s3_feedback_attachments import (
    delete_feedback_attachment,
    upload_feedback_attachment,
)

from .filters import ProjectFeedbackFilter
from .models import FeedbackAuditLog, ProjectFeedback
from .notifications import notify_feedback_created
from .permissions import (
    FeedbackPermission,
    can_change_status,
    can_create_feedback,
    can_delete_feedback,
    can_update_feedback,
)
from .serializers import (
    FeedbackCreateSerializer,
    FeedbackStatusSerializer,
    FeedbackUpdateSerializer,
    ProjectFeedbackSerializer,
)

logger = logging.getLogger(__name__)

PRIORITY_ORDER = Case(
    When(priority=ProjectFeedback.PRIORITY_CRITICAL, then=Value(4)),
    When(priority=ProjectFeedback.PRIORITY_HIGH, then=Value(3)),
    When(priority=ProjectFeedback.PRIORITY_MEDIUM, then=Value(2)),
    When(priority=ProjectFeedback.PRIORITY_LOW, then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)


class FeedbackPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _write_audit(*, feedback, project, action, actor, detail=""):
    FeedbackAuditLog.objects.create(
        feedback=feedback if feedback and feedback.pk else None,
        feedback_id_snapshot=getattr(feedback, "pk", None),
        project=project,
        action=action,
        actor=actor,
        detail=detail or "",
    )


class ProjectFeedbackViewSet(viewsets.ModelViewSet):
    """
    Project Feedback API.

    POST   /api/project-feedback/
    GET    /api/project-feedback/
    GET    /api/project-feedback/{id}/
    PATCH  /api/project-feedback/{id}/
    DELETE /api/project-feedback/{id}/
    PATCH  /api/project-feedback/{id}/status/
    """

    serializer_class = ProjectFeedbackSerializer
    permission_classes = [FeedbackPermission]
    pagination_class = FeedbackPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ProjectFeedbackFilter
    search_fields = ["issue_title", "issue_description", "project__name"]
    ordering_fields = ["created_at", "status", "priority_rank"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            ProjectFeedback.objects.filter(is_active=True)
            .select_related("project", "reported_by", "assigned_team_leader")
            .prefetch_related(
                "reported_by__groups",
                "assigned_team_leader__groups",
            )
            .annotate(priority_rank=PRIORITY_ORDER)
        )
        return filter_queryset_by_project_access(qs, self.request.user, "project")

    def _success(self, message, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    @swagger_auto_schema(
        operation_summary="List project feedback",
        tags=["Project Feedback"],
        manual_parameters=[
            openapi.Parameter("project", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("status", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("priority", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("reported_by", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("created_date", openapi.IN_QUERY, type=openapi.TYPE_STRING, description="YYYY-MM-DD"),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("ordering", openapi.IN_QUERY, type=openapi.TYPE_STRING, description="created_at, -created_at, status, priority_rank, -priority_rank"),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            data = ProjectFeedbackSerializer(page, many=True).data
            paginated = self.get_paginated_response(data)
            return Response(
                {
                    "success": True,
                    "message": "Project feedback retrieved successfully",
                    "data": paginated.data,
                }
            )
        data = ProjectFeedbackSerializer(queryset, many=True).data
        return self._success("Project feedback retrieved successfully", data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self._success(
            "Project feedback retrieved successfully",
            ProjectFeedbackSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Create project feedback",
        tags=["Project Feedback"],
        manual_parameters=[
            openapi.Parameter("project", openapi.IN_FORM, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("issue_title", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("issue_description", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("priority", openapi.IN_FORM, type=openapi.TYPE_STRING, enum=["Low", "Medium", "High", "Critical"]),
            openapi.Parameter("attachment", openapi.IN_FORM, type=openapi.TYPE_FILE),
        ],
    )
    def create(self, request, *args, **kwargs):
        serializer = FeedbackCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        data = serializer.validated_data
        project = data["project"]
        if not can_create_feedback(request.user, project):
            return self._error(
                "You do not have permission to create feedback for this project.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        attachment = data.get("attachment")
        upload_meta = None
        if attachment is not None:
            now = timezone.now()
            try:
                upload_meta = upload_feedback_attachment(
                    uploaded_file=attachment,
                    project_id=project.id,
                    year=now.year,
                    month=now.month,
                )
            except Exception as exc:
                logger.exception("Feedback attachment upload failed")
                return self._error(str(exc) or "Attachment upload failed")

        try:
            with transaction.atomic():
                feedback = ProjectFeedback.objects.create(
                    project=project,
                    issue_title=data["issue_title"],
                    issue_description=data["issue_description"],
                    priority=data.get("priority", ProjectFeedback.PRIORITY_MEDIUM),
                    status=ProjectFeedback.STATUS_OPEN,
                    reported_by=request.user,
                    assigned_team_leader=getattr(project, "team_lead", None),
                    attachment_url=(upload_meta or {}).get("attachment_url", ""),
                    attachment_name=(upload_meta or {}).get("attachment_name", ""),
                    attachment_size=(upload_meta or {}).get("attachment_size", 0),
                    attachment_type=(upload_meta or {}).get("attachment_type", ""),
                    attachment_key=(upload_meta or {}).get("s3_key", ""),
                )
                _write_audit(
                    feedback=feedback,
                    project=project,
                    action=FeedbackAuditLog.ACTION_CREATED,
                    actor=request.user,
                    detail=f"Created feedback '{feedback.issue_title}'",
                )
        except Exception as exc:
            logger.exception("Feedback create failed; rolling back attachment")
            if upload_meta:
                delete_feedback_attachment(upload_meta["s3_key"])
            return self._error(
                "Failed to save feedback",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        notify_feedback_created(feedback)

        return self._success(
            "Feedback created successfully",
            ProjectFeedbackSerializer(feedback).data,
            http_status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_update_feedback(request.user, instance):
            return self._error(
                "You do not have permission to update this feedback.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = FeedbackUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        data = serializer.validated_data
        old_key = None
        new_meta = None
        audit_actions = []

        if "attachment" in data and data["attachment"] is not None:
            now = timezone.now()
            try:
                new_meta = upload_feedback_attachment(
                    uploaded_file=data["attachment"],
                    project_id=instance.project_id,
                    year=now.year,
                    month=now.month,
                )
                old_key = instance.attachment_key
            except Exception as exc:
                return self._error(str(exc) or "Attachment upload failed")

        with transaction.atomic():
            if "issue_title" in data:
                instance.issue_title = data["issue_title"]
            if "issue_description" in data:
                instance.issue_description = data["issue_description"]
            if "remarks" in data:
                instance.remarks = data["remarks"]
            if "priority" in data and data["priority"] != instance.priority:
                instance.priority = data["priority"]
                audit_actions.append(
                    (FeedbackAuditLog.ACTION_PRIORITY_CHANGED, f"Priority set to {data['priority']}")
                )
            if "status" in data and data["status"] != instance.status:
                instance.status = data["status"]
                if data["status"] == ProjectFeedback.STATUS_RESOLVED and not instance.resolved_at:
                    instance.resolved_at = timezone.now()
                audit_actions.append(
                    (FeedbackAuditLog.ACTION_STATUS_CHANGED, f"Status set to {data['status']}")
                )
            if "is_active" in data:
                instance.is_active = data["is_active"]
            if new_meta:
                instance.attachment_url = new_meta["attachment_url"]
                instance.attachment_name = new_meta["attachment_name"]
                instance.attachment_size = new_meta["attachment_size"]
                instance.attachment_type = new_meta["attachment_type"]
                instance.attachment_key = new_meta["s3_key"]
                audit_actions.append(
                    (FeedbackAuditLog.ACTION_ATTACHMENT_UPDATED, "Attachment updated")
                )
            instance.save()

            if not audit_actions:
                audit_actions.append((FeedbackAuditLog.ACTION_UPDATED, "Updated feedback"))
            for act, detail in audit_actions:
                _write_audit(
                    feedback=instance,
                    project=instance.project,
                    action=act,
                    actor=request.user,
                    detail=detail,
                )

        if old_key and old_key != instance.attachment_key:
            delete_feedback_attachment(old_key)

        return self._success(
            "Feedback updated successfully",
            ProjectFeedbackSerializer(instance).data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_delete_feedback(request.user, instance.project):
            return self._error(
                "You do not have permission to delete this feedback.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        project = instance.project
        feedback_id = instance.pk
        title = instance.issue_title
        attachment_key = instance.attachment_key

        with transaction.atomic():
            _write_audit(
                feedback=instance,
                project=project,
                action=FeedbackAuditLog.ACTION_DELETED,
                actor=request.user,
                detail=f"Deleted feedback '{title}'",
            )
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])

        if attachment_key:
            delete_feedback_attachment(attachment_key)

        return self._success(
            f"Feedback '{title}' deleted successfully",
            {"id": feedback_id},
        )

    @swagger_auto_schema(
        operation_summary="Update feedback status (PMC Head / Team Leader / Admin)",
        tags=["Project Feedback"],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"status": openapi.Schema(type=openapi.TYPE_STRING, enum=["Open", "In Progress", "Resolved", "Closed"])},
            required=["status"],
        ),
    )
    @action(detail=True, methods=["patch"], url_path="status")
    def change_status(self, request, pk=None):
        instance = self.get_object()
        if not can_change_status(request.user, instance):
            return self._error(
                "You do not have permission to change the status of this feedback.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = FeedbackStatusSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        new_status = serializer.validated_data["status"]
        with transaction.atomic():
            if new_status != instance.status:
                instance.status = new_status
                if new_status == ProjectFeedback.STATUS_RESOLVED and not instance.resolved_at:
                    instance.resolved_at = timezone.now()
                instance.save(update_fields=["status", "resolved_at", "updated_at"])
                _write_audit(
                    feedback=instance,
                    project=instance.project,
                    action=FeedbackAuditLog.ACTION_STATUS_CHANGED,
                    actor=request.user,
                    detail=f"Status set to {new_status}",
                )

        return self._success(
            "Feedback status updated successfully",
            ProjectFeedbackSerializer(instance).data,
        )
