from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.rbac import (
    filter_queryset_by_project_access,
    get_user_assigned_projects_qs,
    normalize_project_name,
    resolve_project,
)
from projects.models import Project

from .models import MeetingDocument
from .permissions import (
    MeetingDocumentPermission,
    can_delete_meeting_document,
    can_upload_meeting_document,
)
from .serializers import (
    MeetingDocumentDetailSerializer,
    MeetingDocumentPatchSerializer,
    MeetingDocumentSerializer,
    MeetingDocumentUploadSerializer,
)
from .services.notifications import schedule_meeting_document_upload_notification
from .services.storage import (
    build_object_key,
    check_s3_ready,
    delete_document,
    generate_presigned_download_url,
    optimize_upload,
    upload_document,
)

logger = logging.getLogger(__name__)


class MeetingDocumentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _flatten_errors(errors):
    if isinstance(errors, dict):
        flat = {}
        for field, messages in errors.items():
            if isinstance(messages, list):
                flat[field] = " ".join(str(m) for m in messages)
            elif isinstance(messages, dict):
                flat[field] = _flatten_errors(messages)
            else:
                flat[field] = str(messages)
        return flat
    if isinstance(errors, list):
        return {"detail": " ".join(str(m) for m in errors)}
    return {"detail": str(errors)}


class MeetingDocumentViewSet(viewsets.ModelViewSet):
    """
    Meeting document management for MoM and EDL files stored in private S3.
    """

    queryset = MeetingDocument.objects.select_related(
        "project",
        "uploaded_by",
        "created_by",
        "updated_by",
    )
    serializer_class = MeetingDocumentSerializer
    pagination_class = MeetingDocumentPagination
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [MeetingDocumentPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

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

    def get_queryset(self):
        qs = self.queryset.filter(is_active=True)
        params = self.request.query_params

        project_name = params.get("project_name") or params.get("project")
        if project_name:
            qs = qs.filter(project__name__icontains=project_name.strip())

        meeting_type = params.get("meeting_type")
        if meeting_type:
            qs = qs.filter(meeting_type=meeting_type.strip().upper())

        meeting_date = params.get("meeting_date")
        if meeting_date:
            qs = qs.filter(meeting_date=meeting_date)

        uploaded_by = params.get("uploaded_by")
        if uploaded_by:
            if str(uploaded_by).isdigit():
                qs = qs.filter(uploaded_by_id=int(uploaded_by))
            else:
                qs = qs.filter(
                    Q(uploaded_by__username__icontains=uploaded_by.strip())
                    | Q(uploaded_by__first_name__icontains=uploaded_by.strip())
                    | Q(uploaded_by__last_name__icontains=uploaded_by.strip())
                )

        year = params.get("year")
        if year:
            try:
                qs = qs.filter(meeting_date__year=int(year))
            except ValueError:
                pass

        month = params.get("month")
        if month:
            try:
                qs = qs.filter(meeting_date__month=int(month))
            except ValueError:
                pass

        search = params.get("search")
        if search:
            s = search.strip()
            qs = qs.filter(
                Q(title__icontains=s)
                | Q(description__icontains=s)
                | Q(meeting_number__icontains=s)
                | Q(project__name__icontains=s)
                | Q(meeting_type__icontains=s)
            )

        return filter_queryset_by_project_access(qs, self.request.user, "project")

    def _resolve_project_or_error(self, project_name: str):
        project = resolve_project(normalize_project_name(project_name))
        if project is None:
            return None, self._error(
                "Project not found.",
                errors={"project_name": "Project not found."},
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return project, None

    def _next_version(self, *, project, meeting_type, meeting_number, title):
        qs = MeetingDocument.objects.filter(
            project=project,
            meeting_type=meeting_type,
            meeting_number=meeting_number or "",
            title=title,
        )
        current = qs.aggregate(max_version=Max("document_version"))["max_version"]
        return (current or 0) + 1

    def _serialize_with_download_url(self, instance):
        instance._download_url = generate_presigned_download_url(instance.s3_key)
        instance._download_url_expires_in_seconds = 600
        return MeetingDocumentDetailSerializer(instance).data

    @swagger_auto_schema(
        operation_summary="Upload a MoM or EDL document",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("meeting_type", openapi.IN_FORM, type=openapi.TYPE_STRING, enum=["MOM", "EDL"], required=True),
            openapi.Parameter("title", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("description", openapi.IN_FORM, type=openapi.TYPE_STRING),
            openapi.Parameter("meeting_date", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("meeting_number", openapi.IN_FORM, type=openapi.TYPE_STRING),
            openapi.Parameter("document_version", openapi.IN_FORM, type=openapi.TYPE_INTEGER),
            openapi.Parameter("file", openapi.IN_FORM, type=openapi.TYPE_FILE, required=True),
        ],
        tags=["Meeting Documents"],
    )
    def create(self, request, *args, **kwargs):
        ready, storage_message = check_s3_ready()
        if not ready:
            return self._error(
                "Meeting document storage is not configured.",
                errors=storage_message,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = MeetingDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        data = serializer.validated_data
        project, error = self._resolve_project_or_error(data["project_name"])
        if error:
            return error
        if not can_upload_meeting_document(request.user, project):
            return self._error(
                "You do not have permission to upload meeting documents for this project.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        uploaded_file = data["file"]
        uploaded_asset_key = None
        optimized = None

        try:
            optimized = optimize_upload(uploaded_file)
            version = data.get("document_version") or self._next_version(
                project=project,
                meeting_type=data["meeting_type"],
                meeting_number=data.get("meeting_number", ""),
                title=data["title"],
            )
            object_key = build_object_key(
                project_name=project.name,
                meeting_type=data["meeting_type"],
                meeting_date=data["meeting_date"],
                filename=optimized.file_name,
                version=version,
            )
            upload_result = upload_document(optimized, object_key=object_key)
            uploaded_asset_key = upload_result["s3_key"]
            with transaction.atomic():
                document = MeetingDocument.objects.create(
                    project=project,
                    uploaded_by=request.user,
                    meeting_type=data["meeting_type"],
                    title=data["title"],
                    description=data.get("description", ""),
                    meeting_date=data["meeting_date"],
                    meeting_number=data.get("meeting_number", ""),
                    document_version=version,
                    file_name=optimized.file_name,
                    original_file_size=optimized.original_size,
                    compressed_file_size=optimized.compressed_size,
                    compression_percentage=optimized.compression_percentage,
                    content_type=optimized.content_type,
                    s3_key=upload_result["s3_key"],
                    s3_url=upload_result["s3_url"],
                    created_by=request.user,
                    updated_by=request.user,
                )
                schedule_meeting_document_upload_notification(document.id)
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=_flatten_errors(exc.messages))
        except Exception as exc:
            if uploaded_asset_key:
                try:
                    delete_document(uploaded_asset_key)
                except Exception:
                    logger.exception("Failed to roll back S3 object %s", uploaded_asset_key)
            logger.exception("Meeting document upload failed: %s", exc)
            return self._error(
                "Failed to upload meeting document.",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            if optimized is not None:
                try:
                    optimized.file_obj.close()
                except Exception:
                    pass

        return self._success(
            "Meeting document uploaded successfully.",
            MeetingDocumentSerializer(document).data,
            http_status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(operation_summary="List meeting documents", tags=["Meeting Documents"])
    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": "Meeting documents retrieved successfully.",
                    "data": paginated.data,
                }
            )
        return self._success(
            "Meeting documents retrieved successfully.",
            self.get_serializer(qs, many=True).data,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            data = self._serialize_with_download_url(instance)
        except RuntimeError as exc:
            return self._error(
                "Unable to generate download URL.",
                errors=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self._success("Meeting document retrieved successfully.", data)

    def _create_new_version_from_patch(self, request, instance, data):
        ready, storage_message = check_s3_ready()
        if not ready:
            return None, self._error(
                "Meeting document storage is not configured.",
                errors=storage_message,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        uploaded_file = data["file"]
        uploaded_asset_key = None
        optimized = None
        try:
            optimized = optimize_upload(uploaded_file)
            title = data.get("title", instance.title)
            meeting_number = data.get("meeting_number", instance.meeting_number)
            meeting_type = instance.meeting_type
            meeting_date = data.get("meeting_date", instance.meeting_date)
            version = data.get("document_version") or self._next_version(
                project=instance.project,
                meeting_type=meeting_type,
                meeting_number=meeting_number,
                title=title,
            )
            object_key = build_object_key(
                project_name=instance.project.name,
                meeting_type=meeting_type,
                meeting_date=meeting_date,
                filename=optimized.file_name,
                version=version,
            )
            upload_result = upload_document(optimized, object_key=object_key)
            uploaded_asset_key = upload_result["s3_key"]
            with transaction.atomic():
                new_doc = MeetingDocument.objects.create(
                    project=instance.project,
                    uploaded_by=request.user,
                    meeting_type=meeting_type,
                    title=title,
                    description=data.get("description", instance.description),
                    meeting_date=meeting_date,
                    meeting_number=meeting_number,
                    document_version=version,
                    file_name=optimized.file_name,
                    original_file_size=optimized.original_size,
                    compressed_file_size=optimized.compressed_size,
                    compression_percentage=optimized.compression_percentage,
                    content_type=optimized.content_type,
                    s3_key=upload_result["s3_key"],
                    s3_url=upload_result["s3_url"],
                    created_by=request.user,
                    updated_by=request.user,
                )
                schedule_meeting_document_upload_notification(new_doc.id)
            return new_doc, None
        except Exception as exc:
            if uploaded_asset_key:
                try:
                    delete_document(uploaded_asset_key)
                except Exception:
                    logger.exception("Failed to roll back S3 object %s", uploaded_asset_key)
            logger.exception("Meeting document version upload failed: %s", exc)
            return None, self._error(
                "Failed to upload new document version.",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            if optimized is not None:
                try:
                    optimized.file_obj.close()
                except Exception:
                    pass

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_upload_meeting_document(request.user, instance.project):
            return self._error(
                "You do not have permission to update meeting documents for this project.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = MeetingDocumentPatchSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )
        data = serializer.validated_data

        if "file" in data:
            new_doc, error = self._create_new_version_from_patch(request, instance, data)
            if error:
                return error
            return self._success(
                "New meeting document version uploaded successfully.",
                MeetingDocumentSerializer(new_doc).data,
                http_status=status.HTTP_201_CREATED,
            )

        for field in ("title", "description", "meeting_date", "meeting_number"):
            if field in data:
                setattr(instance, field, data[field])
        instance.updated_by = request.user
        instance.save()
        return self._success(
            "Meeting document updated successfully.",
            MeetingDocumentSerializer(instance).data,
        )

    update = partial_update

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_delete_meeting_document(request.user, instance.project):
            return self._error(
                "You do not have permission to delete meeting documents for this project.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        instance.is_active = False
        instance.updated_by = request.user
        instance.save(update_fields=["is_active", "updated_by", "updated_at"])
        return self._success("Meeting document deleted successfully.", {})

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        instance = self.get_object()
        try:
            url = generate_presigned_download_url(instance.s3_key)
        except RuntimeError as exc:
            return self._error(
                "Unable to generate download URL.",
                errors=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self._success(
            "Download URL generated successfully.",
            {
                "id": instance.id,
                "file_name": instance.file_name,
                "download_url": url,
                "expires_in_seconds": 600,
            },
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/]+)",
        url_name="by-project",
    )
    def by_project(self, request, projectName=None):
        project_name = (projectName or "").strip()
        project = Project.objects.filter(name__iexact=project_name).first()
        if project is None:
            return self._error("Project not found.", http_status=status.HTTP_404_NOT_FOUND)

        base_qs = self.get_queryset().filter(project=project).order_by(
            "meeting_type",
            "meeting_number",
            "title",
            "-document_version",
        )
        grouped = {"MOM": [], "EDL": []}
        seen = set()
        for doc in base_qs:
            key = (doc.meeting_type, doc.meeting_number, doc.title)
            item = MeetingDocumentSerializer(doc).data
            if key not in seen:
                item["is_latest_version"] = True
                item["older_versions"] = MeetingDocumentSerializer(
                    base_qs.filter(
                        meeting_type=doc.meeting_type,
                        meeting_number=doc.meeting_number,
                        title=doc.title,
                    ).exclude(pk=doc.pk),
                    many=True,
                ).data
                grouped[doc.meeting_type].append(item)
                seen.add(key)

        return self._success(
            "Project meeting documents retrieved successfully.",
            {
                "project_name": project.name,
                "mom_documents": grouped["MOM"],
                "edl_documents": grouped["EDL"],
            },
        )

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        qs = self.get_queryset()
        now = timezone.now()
        month_qs = qs.filter(uploaded_at__year=now.year, uploaded_at__month=now.month)
        total_original = qs.aggregate(total=Sum("original_file_size"))["total"] or 0
        total_compressed = qs.aggregate(total=Sum("compressed_file_size"))["total"] or 0
        recent = qs.order_by("-uploaded_at")[:5]
        latest_meetings = qs.order_by("-meeting_date", "-document_version")[:5]

        return self._success(
            "Meeting documents dashboard retrieved successfully.",
            {
                "total_mom": qs.filter(meeting_type="MOM").count(),
                "total_edl": qs.filter(meeting_type="EDL").count(),
                "documents_uploaded_this_month": month_qs.count(),
                "recent_uploads": MeetingDocumentSerializer(recent, many=True).data,
                "latest_meetings": MeetingDocumentSerializer(latest_meetings, many=True).data,
                "storage_used": int(total_compressed),
                "storage_saved_through_compression": int(max(total_original - total_compressed, 0)),
            },
        )
