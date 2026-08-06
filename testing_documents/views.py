import logging

from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.rbac import filter_queryset_by_project_access
from services.s3_testing_documents import (
    delete_testing_document,
    generate_presigned_url,
    upload_testing_document,
)

from .models import TestingDocument, TestingDocumentAuditLog
from .permissions import (
    TestingDocumentPermission,
    can_create_testing_document,
    can_delete_testing_document,
    can_update_testing_document,
)
from .serializers import (
    TestingDocumentSerializer,
    TestingDocumentUpdateSerializer,
    TestingDocumentUploadSerializer,
)

logger = logging.getLogger(__name__)


class TestingDocumentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _write_audit(*, document, project, action, actor, detail: str = "") -> None:
    TestingDocumentAuditLog.objects.create(
        document=document if document and document.pk else None,
        document_id_snapshot=getattr(document, "pk", None),
        project=project,
        action=action,
        actor=actor,
        detail=detail or "",
    )


class TestingDocumentViewSet(viewsets.ModelViewSet):
    """
    Testing Documents API — PDF / image / video uploads to private S3.

    POST   /api/testing-documents/
    GET    /api/testing-documents/
    GET    /api/testing-documents/{id}/
    PATCH  /api/testing-documents/{id}/
    DELETE /api/testing-documents/{id}/
    GET    /api/testing-documents/{id}/download/
    """

    queryset = TestingDocument.objects.select_related(
        "project",
        "uploaded_by",
    )
    serializer_class = TestingDocumentSerializer
    permission_classes = [TestingDocumentPermission]
    pagination_class = TestingDocumentPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "project": ["exact"],
        "month": ["exact"],
        "year": ["exact"],
        "document_type": ["exact"],
        "uploaded_by": ["exact"],
    }
    search_fields = [
        "title",
        "remarks",
        "project__name",
        "uploaded_by__username",
        "uploaded_by__first_name",
        "uploaded_by__last_name",
    ]
    ordering_fields = ["created_at", "test_date", "title", "file_name"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = TestingDocument.objects.filter(is_active=True).select_related(
            "project",
            "uploaded_by",
        ).prefetch_related(
            "uploaded_by__groups",
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
        operation_summary="List testing documents",
        tags=["Testing Documents"],
        manual_parameters=[
            openapi.Parameter("project", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("document_type", openapi.IN_QUERY, type=openapi.TYPE_STRING, enum=["pdf", "image", "video"]),
            openapi.Parameter("uploaded_by", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("search", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("ordering", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            data = TestingDocumentSerializer(page, many=True).data
            paginated = self.get_paginated_response(data)
            return Response(
                {
                    "success": True,
                    "message": "Testing documents retrieved successfully",
                    "data": paginated.data,
                }
            )
        data = TestingDocumentSerializer(queryset, many=True).data
        return self._success("Testing documents retrieved successfully", data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return self._success(
            "Testing document retrieved successfully",
            TestingDocumentSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Upload a testing document (PDF / image / video)",
        manual_parameters=[
            openapi.Parameter("project", openapi.IN_FORM, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("title", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("remarks", openapi.IN_FORM, type=openapi.TYPE_STRING),
            openapi.Parameter("test_date", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True, description="YYYY-MM-DD"),
            openapi.Parameter("file", openapi.IN_FORM, type=openapi.TYPE_FILE, required=True),
        ],
        tags=["Testing Documents"],
    )
    def create(self, request, *args, **kwargs):
        serializer = TestingDocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        project = serializer.validated_data["project"]
        if not can_create_testing_document(request.user, project):
            return self._error(
                "You do not have permission to upload testing documents for this project.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        test_date = serializer.validated_data["test_date"]
        uploaded = serializer.validated_data["file"]
        title = serializer.validated_data["title"]
        remarks = serializer.validated_data.get("remarks") or ""

        try:
            upload_meta = upload_testing_document(
                uploaded_file=uploaded,
                project_id=project.id,
                year=test_date.year,
                month=test_date.month,
            )
        except Exception as exc:
            logger.exception("Testing document S3 upload failed")
            return self._error(str(exc) or "Upload failed")

        try:
            with transaction.atomic():
                doc = TestingDocument.objects.create(
                    project=project,
                    title=title,
                    remarks=remarks,
                    file=upload_meta["s3_key"],
                    file_url=upload_meta["file_url"],
                    file_name=upload_meta["file_name"],
                    file_size=upload_meta["file_size"],
                    mime_type=upload_meta["mime_type"],
                    document_type=upload_meta["document_type"],
                    test_date=test_date,
                    month=test_date.month,
                    year=test_date.year,
                    uploaded_by=request.user,
                )
                _write_audit(
                    document=doc,
                    project=project,
                    action=TestingDocumentAuditLog.ACTION_CREATED,
                    actor=request.user,
                    detail=f"Uploaded {doc.file_name}",
                )
        except Exception as exc:
            logger.exception("Testing document DB create failed; rolling back S3 object")
            delete_testing_document(upload_meta["s3_key"])
            return self._error(
                "Failed to save testing document",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return self._success(
            "Testing document uploaded successfully",
            TestingDocumentSerializer(doc).data,
            http_status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_update_testing_document(request.user, instance):
            return self._error(
                "You do not have permission to update this testing document.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TestingDocumentUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self._error("Validation failed", errors=serializer.errors)

        data = serializer.validated_data
        old_key = None
        new_meta = None

        if "file" in data and data["file"] is not None:
            test_date = data.get("test_date") or instance.test_date
            try:
                new_meta = upload_testing_document(
                    uploaded_file=data["file"],
                    project_id=instance.project_id,
                    year=test_date.year,
                    month=test_date.month,
                )
                old_key = instance.file
            except Exception as exc:
                return self._error(str(exc) or "Upload failed")

        with transaction.atomic():
            if "title" in data:
                instance.title = data["title"]
            if "remarks" in data:
                instance.remarks = data["remarks"]
            if "test_date" in data:
                instance.test_date = data["test_date"]
                instance.month = data["test_date"].month
                instance.year = data["test_date"].year
            if "is_active" in data:
                instance.is_active = data["is_active"]
            if new_meta:
                instance.file = new_meta["s3_key"]
                instance.file_url = new_meta["file_url"]
                instance.file_name = new_meta["file_name"]
                instance.file_size = new_meta["file_size"]
                instance.mime_type = new_meta["mime_type"]
                instance.document_type = new_meta["document_type"]
            instance.save()
            _write_audit(
                document=instance,
                project=instance.project,
                action=TestingDocumentAuditLog.ACTION_UPDATED,
                actor=request.user,
                detail="Updated testing document",
            )

        if old_key and old_key != instance.file:
            delete_testing_document(old_key)

        return self._success(
            "Testing document updated successfully",
            TestingDocumentSerializer(instance).data,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not can_delete_testing_document(request.user, instance.project):
            return self._error(
                "You do not have permission to delete this testing document.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        s3_key = instance.file
        project = instance.project
        doc_id = instance.pk
        title = instance.title

        with transaction.atomic():
            _write_audit(
                document=instance,
                project=project,
                action=TestingDocumentAuditLog.ACTION_DELETED,
                actor=request.user,
                detail=f"Deleted {title}",
            )
            # Soft-delete to preserve audit FK where possible
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])

        delete_testing_document(s3_key)
        return self._success(
            f"Testing document '{title}' deleted successfully",
            {"id": doc_id},
        )

    @swagger_auto_schema(
        operation_summary="Get pre-signed download / preview URL",
        tags=["Testing Documents"],
    )
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        instance = self.get_object()
        try:
            url = generate_presigned_url(instance.file)
        except Exception as exc:
            logger.warning("Presign failed; falling back to stored URL: %s", exc)
            url = instance.file_url
        return self._success(
            "Download URL generated successfully",
            {
                "id": instance.id,
                "file_name": instance.file_name,
                "document_type": instance.document_type,
                "mime_type": instance.mime_type,
                "download_url": url,
                "preview": instance.document_type in ("pdf", "image", "video"),
            },
        )
