"""
Site Progress Images API — AWS S3 primary, Cloudinary fallback.
"""

import logging

from django.db import transaction
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from accounts.rbac_checks import enforce_project_write_by_name
from core.cache_tags import invalidate_tags
from .models import SiteProgressImage
from .serializers import (
    SiteProgressImageSerializer,
    SiteProgressImageUploadSerializer,
    normalize_title,
)
from .services.image_storage import (
    build_upload_folder,
    check_storage_ready,
    delete_image,
    upload_image,
)

logger = logging.getLogger(__name__)


class SiteImagePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _collect_upload_files(request) -> list:
    """
    Accept multipart file fields from the frontend:
      - images (multiple)
      - images[] (multiple, FormData convention)
      - any key starting with 'images'
    """
    if not request.FILES:
        return []

    collected: list = []
    seen_ids: set[int] = set()

    def _add(file_list):
        for f in file_list:
            fid = id(f)
            if fid not in seen_ids:
                seen_ids.add(fid)
                collected.append(f)

    for key in ("images", "images[]"):
        _add(request.FILES.getlist(key))

    if not collected:
        for key in sorted(request.FILES.keys()):
            if key == "images" or key.startswith("images"):
                _add(request.FILES.getlist(key))

    return collected


def _getlist(data, *keys) -> list:
    """Collect list values from QueryDict / dict-like multipart payloads."""
    for key in keys:
        if hasattr(data, "getlist"):
            values = data.getlist(key)
            if values:
                return list(values)
        elif isinstance(data, dict) and key in data:
            value = data.get(key)
            if isinstance(value, (list, tuple)):
                return list(value)
            if value is not None:
                return [value]
    return []


def _collect_titles(request, count: int) -> list[str]:
    """
    Resolve per-image titles from multipart form data.

    Priority:
      1. titles[] / titles  — map by index (missing indexes → "")
      2. title              — apply the same title to every image
      3. neither            — empty string for every image
    """
    data = request.data
    titled = _getlist(data, "titles", "titles[]")
    if titled:
        result: list[str] = []
        for i in range(count):
            raw = titled[i] if i < len(titled) else ""
            result.append(normalize_title(raw))
        return result

    single = ""
    if hasattr(data, "get"):
        single = data.get("title")
    normalized = normalize_title(single)
    if normalized:
        return [normalized] * count
    return [""] * count


def _invalidate_site_image_cache() -> None:
    """Bump only site-image list cache version (no unrelated flush)."""
    invalidate_tags("site_images")


def _flatten_errors(errors) -> dict:
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


class SiteProgressImageViewSet(viewsets.ModelViewSet):
    """
    Site photos stored in AWS S3 (Cloudinary fallback).

    POST   /api/site-images/          — multi-image upload (multipart)
    GET    /api/site-images/          — paginated gallery
    GET    /api/site-images/{id}/
    PATCH  /api/site-images/{id}/     — update title only
    DELETE /api/site-images/{id}/     — removes storage asset + DB row
    """

    queryset = SiteProgressImage.objects.all()
    serializer_class = SiteProgressImageSerializer
    pagination_class = SiteImagePagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["title", "project_name"]
    ordering_fields = ["title", "created_at", "month", "year"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.ENGINEERING

    def get_queryset(self):
        qs = SiteProgressImage.objects.all()
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name.strip())

        month = self.request.query_params.get("month")
        if month:
            try:
                qs = qs.filter(month=int(month))
            except ValueError:
                pass

        year = self.request.query_params.get("year")
        if year:
            try:
                qs = qs.filter(year=int(year))
            except ValueError:
                pass

        # Explicit title filter (in addition to SearchFilter ?search=)
        title = self.request.query_params.get("title")
        if title:
            qs = qs.filter(title__icontains=title.strip())

        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            qs = filter_queryset_by_project_access(qs, user, "project_name")

        return qs

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    @swagger_auto_schema(
        operation_summary="Upload site progress images",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_FORM, type=openapi.TYPE_STRING, required=True),
            openapi.Parameter("month", openapi.IN_FORM, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter("year", openapi.IN_FORM, type=openapi.TYPE_INTEGER, required=True),
            openapi.Parameter(
                "title",
                openapi.IN_FORM,
                type=openapi.TYPE_STRING,
                required=False,
                description="Optional title applied to every uploaded image",
            ),
            openapi.Parameter(
                "titles",
                openapi.IN_FORM,
                type=openapi.TYPE_STRING,
                required=False,
                description="Optional per-image titles (titles[]), mapped by index",
            ),
            openapi.Parameter(
                "images",
                openapi.IN_FORM,
                type=openapi.TYPE_FILE,
                required=True,
                description="One or more image files (max 20, jpg/jpeg/png/webp, 10MB each)",
            ),
        ],
        tags=["Site Images"],
    )
    def create(self, request, *args, **kwargs):
        ready, storage_message = check_storage_ready()
        if not ready:
            return self._error(
                "Image storage is not configured (AWS S3 or Cloudinary required)",
                errors=storage_message,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        files = _collect_upload_files(request)
        if not files:
            return self._error(
                "Validation failed",
                errors={"images": "At least one image file is required (images or images[])."},
            )

        meta_serializer = SiteProgressImageUploadSerializer(data=request.data)
        if not meta_serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(meta_serializer.errors),
            )

        enforce_project_write_by_name(
            request.user,
            meta_serializer.validated_data.get("project_name"),
            RBACDomain.ENGINEERING,
        )

        try:
            SiteProgressImageUploadSerializer.validate_files(files)
        except Exception as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            if isinstance(exc, DRFValidationError):
                detail = exc.detail
                if isinstance(detail, list):
                    errors = {"images": " ".join(str(d) for d in detail)}
                else:
                    errors = _flatten_errors(detail)
                return self._error("Validation failed", errors=errors)
            return self._error("Validation failed", errors={"images": str(exc)})

        try:
            titles = _collect_titles(request, len(files))
        except Exception as exc:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            if isinstance(exc, DRFValidationError):
                return self._error(
                    "Validation failed",
                    errors=_flatten_errors({"title": exc.detail}),
                )
            return self._error("Validation failed", errors={"title": str(exc)})

        project_name = meta_serializer.validated_data["project_name"]
        month = meta_serializer.validated_data["month"]
        year = meta_serializer.validated_data["year"]
        folder = build_upload_folder(project_name, year, month)

        uploaded_assets: list[tuple[str, str]] = []
        pending_records: list[SiteProgressImage] = []

        try:
            with transaction.atomic():
                for index, uploaded_file in enumerate(files):
                    try:
                        result = upload_image(uploaded_file, folder=folder)
                    except ValueError as exc:
                        raise ValueError(str(exc)) from exc

                    storage_key = result["public_id"]
                    storage_backend = result.get(
                        "storage_backend",
                        SiteProgressImage.STORAGE_S3,
                    )
                    uploaded_assets.append((storage_key, storage_backend))
                    pending_records.append(
                        SiteProgressImage(
                            project_name=project_name,
                            month=month,
                            year=year,
                            title=titles[index] if index < len(titles) else "",
                            image_url=result["secure_url"],
                            cloudinary_public_id=storage_key,
                            storage_backend=storage_backend,
                            uploaded_by=(
                                request.user if request.user.is_authenticated else None
                            ),
                        )
                    )

                created_records = SiteProgressImage.objects.bulk_create(pending_records)
        except ValueError as exc:
            for storage_key, storage_backend in uploaded_assets:
                try:
                    delete_image(storage_key, storage_backend)
                except Exception:
                    logger.exception(
                        "Failed to roll back %s asset %s",
                        storage_backend,
                        storage_key,
                    )
            return self._error("Validation failed", errors={"images": str(exc)})
        except RuntimeError as exc:
            for storage_key, storage_backend in uploaded_assets:
                try:
                    delete_image(storage_key, storage_backend)
                except Exception:
                    logger.exception(
                        "Failed to roll back %s asset %s",
                        storage_backend,
                        storage_key,
                    )
            msg = str(exc)
            if "configuration missing" in msg.lower():
                return self._error(
                    "Image storage configuration missing",
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return self._error(
                "Failed to upload images",
                errors=msg,
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            for storage_key, storage_backend in uploaded_assets:
                try:
                    delete_image(storage_key, storage_backend)
                except Exception:
                    logger.exception(
                        "Failed to roll back %s asset %s",
                        storage_backend,
                        storage_key,
                    )
            logger.exception("Site image upload failed: %s", exc)
            return self._error(
                "Failed to upload images",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        _invalidate_site_image_cache()

        data = [
            {
                "id": record.id,
                "title": record.title or "",
                "image_url": record.image_url,
                "public_id": record.cloudinary_public_id,
                "storage_backend": record.storage_backend,
            }
            for record in created_records
        ]
        return self._success(
            "Images uploaded successfully",
            data,
            http_status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        operation_summary="List site images (paginated)",
        manual_parameters=[
            openapi.Parameter("project_name", openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter("month", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter("year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
            openapi.Parameter(
                "title",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Case-insensitive title filter",
            ),
            openapi.Parameter(
                "search",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Case-insensitive search across title and project_name",
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Order by title, created_at, month, or year (prefix - for desc)",
            ),
        ],
        tags=["Site Images"],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": "Site images retrieved successfully",
                    "data": paginated.data,
                }
            )

        serializer = self.get_serializer(queryset, many=True)
        return self._success(
            "Site images retrieved successfully",
            serializer.data,
        )

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Exception:
            return self._error(
                "Site image not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return self._success(
            "Site image retrieved successfully",
            self.get_serializer(instance).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """Update title without requiring image re-upload."""
        try:
            instance = self.get_object()
        except Exception:
            return self._error(
                "Site image not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_project_write_by_name(
            request.user,
            instance.project_name,
            RBACDomain.ENGINEERING,
        )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if not serializer.is_valid():
            return self._error(
                "Validation failed",
                errors=_flatten_errors(serializer.errors),
            )

        # Only persist title — ignore any other writable attempt
        title = serializer.validated_data.get("title", instance.title or "")
        instance.title = title or ""
        instance.save(update_fields=["title", "updated_at"])
        _invalidate_site_image_cache()

        return self._success(
            "Site image updated successfully",
            self.get_serializer(instance).data,
        )

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Exception:
            return self._error(
                "Site image not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        storage_key = instance.cloudinary_public_id
        storage_backend = instance.storage_backend
        try:
            delete_image(storage_key, storage_backend)
        except Exception as exc:
            logger.exception(
                "%s delete failed for %s: %s",
                storage_backend,
                storage_key,
                exc,
            )
            return self._error(
                f"Failed to delete image from {storage_backend}",
                errors=str(exc),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

        instance.delete()
        _invalidate_site_image_cache()
        return self._success("Site image deleted successfully", {})

    @swagger_auto_schema(
        operation_summary="Gallery for project + month + year",
        tags=["Site Images"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/]+)/month/(?P<month>\d+)/year/(?P<year>\d+)",
        url_name="by-project-month-year",
    )
    def by_project_month_year(self, request, projectName=None, month=None, year=None):
        try:
            month_int = int(month)
            year_int = int(year)
        except (TypeError, ValueError):
            return self._error("month and year must be valid integers.")

        if not (1 <= month_int <= 12):
            return self._error("month must be between 1 and 12.")
        if not (2000 <= year_int <= 2100):
            return self._error("year must be between 2000 and 2100.")

        project_name = (projectName or "").strip()
        if not project_name:
            return self._error("projectName is required.")

        qs = SiteProgressImage.objects.filter(
            project_name__iexact=project_name,
            month=month_int,
            year=year_int,
        ).order_by("-created_at")

        if not qs.exists():
            return self._error(
                f"No images found for '{project_name}' in {month_int:02d}/{year_int}.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": (
                        f"Site images for '{project_name}' "
                        f"({month_int:02d}/{year_int}) retrieved successfully"
                    ),
                    "data": paginated.data,
                }
            )

        serializer = self.get_serializer(qs, many=True)
        return self._success(
            f"Site images for '{project_name}' ({month_int:02d}/{year_int}) retrieved successfully",
            serializer.data,
        )

    @swagger_auto_schema(
        operation_summary="Gallery for a project (all months)",
        tags=["Site Images"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/]+)",
        url_name="by-project",
    )
    def by_project(self, request, projectName=None):
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        qs = SiteProgressImage.objects.filter(
            project_name__iexact=projectName.strip()
        ).order_by("-created_at")

        if not qs.exists():
            return self._error(
                f"No images found for project '{projectName.strip()}'.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": f"Site images for '{projectName.strip()}' retrieved successfully",
                    "data": paginated.data,
                }
            )

        serializer = self.get_serializer(qs, many=True)
        return self._success(
            f"Site images for '{projectName.strip()}' retrieved successfully",
            serializer.data,
        )
