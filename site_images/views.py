"""
Site Progress Images API — Cloudinary-backed gallery.
"""

import logging

from django.db import transaction
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import SiteProgressImage
from .serializers import (
    SiteProgressImageSerializer,
    SiteProgressImageUploadSerializer,
)
from .services.cloudinary_service import (
    build_upload_folder,
    check_cloudinary_ready,
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
    Site photos stored in Cloudinary.

    POST   /api/site-images/          — multi-image upload (multipart)
    GET    /api/site-images/          — paginated gallery
    GET    /api/site-images/{id}/
    DELETE /api/site-images/{id}/     — removes Cloudinary asset + DB row
    """

    queryset = SiteProgressImage.objects.all()
    serializer_class = SiteProgressImageSerializer
    permission_classes = [AllowAny]
    pagination_class = SiteImagePagination
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

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

        return qs.order_by("-created_at")

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
        ready, cloudinary_message = check_cloudinary_ready()
        if not ready:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
            if "not installed" in cloudinary_message.lower():
                return self._error(
                    "Cloudinary Python package is not installed",
                    errors=cloudinary_message,
                    http_status=http_status,
                )
            return self._error(
                cloudinary_message,
                http_status=http_status,
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

        project_name = meta_serializer.validated_data["project_name"]
        month = meta_serializer.validated_data["month"]
        year = meta_serializer.validated_data["year"]
        folder = build_upload_folder(project_name, year, month)

        uploaded_public_ids: list[str] = []
        created_records: list[SiteProgressImage] = []

        try:
            with transaction.atomic():
                for uploaded_file in files:
                    try:
                        result = upload_image(uploaded_file, folder=folder)
                    except ValueError as exc:
                        raise ValueError(str(exc)) from exc

                    uploaded_public_ids.append(result["public_id"])
                    record = SiteProgressImage.objects.create(
                        project_name=project_name,
                        month=month,
                        year=year,
                        image_url=result["secure_url"],
                        cloudinary_public_id=result["public_id"],
                        uploaded_by=request.user if request.user.is_authenticated else None,
                    )
                    created_records.append(record)
        except ValueError as exc:
            for pid in uploaded_public_ids:
                try:
                    delete_image(pid)
                except Exception:
                    logger.exception("Failed to roll back Cloudinary asset %s", pid)
            return self._error("Validation failed", errors={"images": str(exc)})
        except RuntimeError as exc:
            for pid in uploaded_public_ids:
                try:
                    delete_image(pid)
                except Exception:
                    logger.exception("Failed to roll back Cloudinary asset %s", pid)
            msg = str(exc)
            if "configuration missing" in msg.lower():
                return self._error(
                    "Cloudinary configuration missing",
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return self._error(
                "Failed to upload images",
                errors=msg,
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            for pid in uploaded_public_ids:
                try:
                    delete_image(pid)
                except Exception:
                    logger.exception("Failed to roll back Cloudinary asset %s", pid)
            logger.exception("Site image upload failed: %s", exc)
            return self._error(
                "Failed to upload images",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        data = [
            {
                "id": record.id,
                "image_url": record.image_url,
                "public_id": record.cloudinary_public_id,
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

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Exception:
            return self._error(
                "Site image not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        public_id = instance.cloudinary_public_id
        try:
            delete_image(public_id)
        except Exception as exc:
            logger.exception("Cloudinary delete failed for %s: %s", public_id, exc)
            return self._error(
                "Failed to delete image from Cloudinary",
                errors=str(exc),
                http_status=status.HTTP_502_BAD_GATEWAY,
            )

        instance.delete()
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
