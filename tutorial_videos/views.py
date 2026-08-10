"""
Tutorial Video ViewSet — section-aware list/create/update.

POST   /api/tutorial-videos/          → 202 Accepted (queued)
GET    /api/tutorial-videos/          → optional ?section=
GET    /api/tutorial-videos/{id}/
PATCH  /api/tutorial-videos/{id}/
DELETE /api/tutorial-videos/{id}/
GET    /api/tutorial-videos/{id}/view/
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.business_audit import write_business_audit
from core.cache_keys import build_rbac_list_cache_key
from core.models import BusinessAuditLog
from tutorial_videos.models import TutorialVideo
from tutorial_videos.permissions import TutorialVideoPermission
from tutorial_videos.processing import (
    CACHE_PREFIX,
    invalidate_tutorial_caches,
    queue_processing_after_commit,
    soft_delete_tutorial_video,
)
from tutorial_videos.sections import is_valid_section, normalize_section
from tutorial_videos.serializers import (
    TutorialVideoCreateResponseSerializer,
    TutorialVideoDetailSerializer,
    TutorialVideoListSerializer,
    TutorialVideoPatchSerializer,
    TutorialVideoUploadSerializer,
)

logger = logging.getLogger("pmc.tutorial_videos")


class TutorialVideoPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "message": "Tutorial videos retrieved successfully.",
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "data": data,
            }
        )


def _section_error_payload():
    return [
        {"field": "section", "message": "Invalid tutorial section."}
    ]


class TutorialVideoViewSet(viewsets.ModelViewSet):
    permission_classes = [TutorialVideoPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = TutorialVideoPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    queryset = TutorialVideo.objects.all()

    def get_queryset(self):
        qs = TutorialVideo.objects.filter(is_active=True).exclude(
            status=TutorialVideo.STATUS_DELETED
        )
        # Section filter applied in list() after validation (avoids silent empty lists).
        status_filter = (self.request.query_params.get("status") or "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
        ordering = (self.request.query_params.get("ordering") or "").strip()
        allowed_ordering = {
            "created_at",
            "-created_at",
            "title",
            "-title",
            "status",
            "-status",
        }
        if ordering in allowed_ordering:
            return qs.order_by(ordering)
        return qs.order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return TutorialVideoUploadSerializer
        if self.action in ("partial_update", "update"):
            return TutorialVideoPatchSerializer
        if self.action == "retrieve":
            return TutorialVideoDetailSerializer
        return TutorialVideoListSerializer

    def _success(self, message, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message, errors=None, http_status=status.HTTP_400_BAD_REQUEST, data=None):
        body = {"success": False, "message": message}
        if errors is not None:
            body["errors"] = errors
        if data is not None:
            body["data"] = data
        return Response(body, status=http_status)

    def _resolve_list_section(self):
        """
        Return (section_key|None, error_response|None).
        Missing section → global list. Invalid section → 400.
        """
        raw = self.request.query_params.get("section", None)
        if raw is None or str(raw).strip() == "":
            return None, None
        key = normalize_section(raw)
        if not is_valid_section(key):
            return None, self._error(
                "Invalid tutorial section.",
                errors=_section_error_payload(),
            )
        return key, None

    def list(self, request, *args, **kwargs):
        section, err = self._resolve_list_section()
        if err is not None:
            return err

        # Cache key includes query string (section, page, page_size, search, ordering).
        cache_key = build_rbac_list_cache_key(CACHE_PREFIX, request)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        queryset = self.filter_queryset(self.get_queryset())
        if section:
            queryset = queryset.filter(section=section)

        page = self.paginate_queryset(queryset)
        ser = TutorialVideoListSerializer(
            page if page is not None else queryset, many=True
        )
        if page is not None:
            response = self.get_paginated_response(ser.data)
            cache.set(cache_key, response.data, 300)
            return response
        payload = {
            "success": True,
            "message": "Tutorial videos retrieved successfully.",
            "count": len(ser.data),
            "data": ser.data,
        }
        cache.set(cache_key, payload, 300)
        return Response(payload)

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_queryset().get(pk=kwargs["pk"])
        except TutorialVideo.DoesNotExist:
            return self._error(
                "Tutorial video not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Tutorial video retrieved successfully.",
            TutorialVideoDetailSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Upload a tutorial video (queued for async compression)",
        manual_parameters=[
            openapi.Parameter(
                "title", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True
            ),
            openapi.Parameter(
                "description", openapi.IN_FORM, type=openapi.TYPE_STRING, required=False
            ),
            openapi.Parameter(
                "section", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True
            ),
            openapi.Parameter(
                "upload", openapi.IN_FORM, type=openapi.TYPE_FILE, required=True
            ),
        ],
        tags=["Tutorial Videos"],
    )
    def create(self, request, *args, **kwargs):
        from services import s3_tutorial_videos as s3
        from tutorial_videos.video_executor import queue_is_full

        ready, storage_message = s3.check_s3_ready()
        if not ready:
            return self._error(
                "Tutorial video storage is not configured.",
                errors=storage_message,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if queue_is_full():
            return self._error(
                "Video processing queue is full. Please try again later.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = TutorialVideoUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return self._error("Validation failed.", errors=serializer.errors)

        uploaded = serializer.validated_data["upload"]
        title = serializer.validated_data["title"]
        description = serializer.validated_data.get("description") or ""
        section = serializer.validated_data["section"]

        try:
            filename, content_type = s3.validate_upload_file(uploaded)
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            return self._error(
                "Validation failed.",
                errors={"upload": " ".join(str(m) for m in messages)},
            )

        temp_key = s3.build_temp_key(filename=filename)
        try:
            size = s3.upload_bytes_or_fileobj(
                fileobj=uploaded,
                s3_key=temp_key,
                content_type=content_type,
                metadata={
                    "original-filename": filename[:200],
                    "section": section,
                },
            )
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None) or [str(exc)]
            return self._error(
                "Upload failed.",
                errors={"upload": " ".join(str(m) for m in messages)},
            )
        except Exception:
            logger.exception("Tutorial temp S3 upload failed")
            return self._error(
                "Failed to store uploaded video.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            with transaction.atomic():
                video = TutorialVideo.objects.create(
                    title=title,
                    description=description,
                    section=section,
                    status=TutorialVideo.STATUS_PROCESSING,
                    temp_s3_key=temp_key,
                    original_filename=filename,
                    original_file_size=size,
                    original_content_type=content_type,
                    created_by=request.user
                    if request.user and request.user.is_authenticated
                    else None,
                )
                queue_processing_after_commit(video.pk)
        except Exception:
            s3.delete_object(temp_key)
            logger.exception("Tutorial video DB create failed")
            return self._error(
                "Failed to create tutorial video record.",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        invalidate_tutorial_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_UPLOADED,
            actor=request.user,
            entity_id=video.pk,
            detail=f"Tutorial video uploaded title={title!r} section={section}",
        )
        logger.info(
            "Upload accepted video_id=%s title=%r section=%s size=%s",
            video.pk,
            title,
            section,
            size,
        )

        return self._success(
            "Tutorial video uploaded and queued for processing.",
            TutorialVideoCreateResponseSerializer(video).data,
            http_status=status.HTTP_202_ACCEPTED,
        )

    def partial_update(self, request, *args, **kwargs):
        try:
            instance = self.get_queryset().get(pk=kwargs["pk"])
        except TutorialVideo.DoesNotExist:
            return self._error(
                "Tutorial video not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TutorialVideoPatchSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self._error("Validation failed.", errors=serializer.errors)

        data = serializer.validated_data
        if not data:
            return self._error("No updatable fields provided.")

        old_section = instance.section
        update_fields = ["updated_at"]
        if "title" in data:
            instance.title = data["title"]
            update_fields.append("title")
        if "description" in data:
            instance.description = data["description"]
            update_fields.append("description")
        if "section" in data:
            instance.section = data["section"]
            update_fields.append("section")

        instance.save(update_fields=update_fields)

        invalidate_tutorial_caches()
        detail = f"Tutorial video metadata updated title={instance.title!r} section={instance.section}"
        if "section" in data and data["section"] != old_section:
            detail = (
                f"Tutorial video section changed id={instance.pk} "
                f"old_section={old_section} new_section={instance.section}"
            )
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_UPDATED,
            actor=request.user,
            entity_id=instance.pk,
            detail=detail,
        )
        return self._success(
            "Tutorial video updated successfully.",
            TutorialVideoDetailSerializer(instance).data,
        )

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_queryset().get(pk=kwargs["pk"])
        except TutorialVideo.DoesNotExist:
            return self._error(
                "Tutorial video not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        title = instance.title
        section = instance.section
        pk = instance.pk
        soft_delete_tutorial_video(instance)
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_DELETED,
            actor=request.user,
            entity_id=pk,
            detail=f"Tutorial video deleted title={title!r} section={section}",
        )
        return self._success(
            "Tutorial video deleted successfully.",
            {"id": pk},
        )

    @swagger_auto_schema(
        operation_summary="Get playback URL for a ready tutorial video",
        tags=["Tutorial Videos"],
    )
    @action(detail=True, methods=["get"], url_path="view")
    def view_video(self, request, pk=None):
        try:
            instance = self.get_queryset().get(pk=pk)
        except TutorialVideo.DoesNotExist:
            return self._error(
                "Tutorial video not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if instance.status == TutorialVideo.STATUS_PROCESSING:
            return self._error(
                "Tutorial video is still being processed.",
                data={"status": instance.status},
                http_status=status.HTTP_409_CONFLICT,
            )
        if instance.status == TutorialVideo.STATUS_FAILED:
            return self._error(
                "Tutorial video processing failed.",
                data={"status": instance.status},
                http_status=status.HTTP_409_CONFLICT,
            )
        if instance.status != TutorialVideo.STATUS_READY or not instance.optimized_s3_key:
            return self._error(
                "Tutorial video is not available for playback.",
                data={"status": instance.status},
                http_status=status.HTTP_409_CONFLICT,
            )

        use_presign = getattr(settings, "TUTORIAL_VIDEO_USE_PRESIGNED", False)
        video_url = instance.video_url
        if use_presign:
            try:
                from services import s3_tutorial_videos as s3

                video_url = s3.generate_presigned_url(instance.optimized_s3_key)
            except Exception:
                logger.exception("Presign failed video_id=%s", instance.pk)
                if not video_url:
                    return self._error(
                        "Unable to generate playback URL.",
                        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
        elif not video_url:
            from services import s3_tutorial_videos as s3

            video_url = s3.object_url(instance.optimized_s3_key)

        return self._success(
            "Tutorial video URL retrieved successfully.",
            {
                "id": instance.id,
                "title": instance.title,
                "video_url": video_url,
            },
        )

    @swagger_auto_schema(
        operation_summary="Re-queue a failed tutorial video for processing",
        tags=["Tutorial Videos"],
    )
    @action(detail=True, methods=["post"], url_path="reprocess")
    def reprocess(self, request, pk=None):
        """Retry FFmpeg/S3 processing when a temporary upload is still available."""
        try:
            instance = self.get_queryset().get(pk=pk)
        except TutorialVideo.DoesNotExist:
            return self._error(
                "Tutorial video not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if instance.status == TutorialVideo.STATUS_READY and instance.optimized_s3_key:
            return self._error("Tutorial video is already ready.")
        if not (instance.temp_s3_key or "").strip():
            return self._error(
                "Temporary upload is missing. Please upload the video again.",
                http_status=status.HTTP_409_CONFLICT,
            )

        from tutorial_videos.video_executor import queue_is_full

        if queue_is_full():
            return self._error(
                "Video processing queue is full. Please try again later.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        instance.status = TutorialVideo.STATUS_PROCESSING
        instance.processing_error = ""
        instance.save(update_fields=["status", "processing_error", "updated_at"])
        queue_processing_after_commit(instance.pk)
        invalidate_tutorial_caches()
        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
            action=BusinessAuditLog.ACTION_UPDATED,
            actor=request.user,
            entity_id=instance.pk,
            detail=(
                f"Tutorial video reprocess queued id={instance.pk} "
                f"section={instance.section}"
            ),
        )
        return self._success(
            "Tutorial video queued for reprocessing.",
            TutorialVideoCreateResponseSerializer(instance).data,
            http_status=status.HTTP_202_ACCEPTED,
        )
