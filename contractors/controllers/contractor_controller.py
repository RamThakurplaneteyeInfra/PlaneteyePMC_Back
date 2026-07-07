"""Contractor Master API controller."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain
from accounts.rbac_checks import enforce_instance_write, enforce_project_access, enforce_project_write
from projects.models import Project

from ..models import Contractor
from .contractor_serializer import (
    ContractorCreateSerializer,
    ContractorListSerializer,
    ContractorSerializer,
    ContractorUpdateSerializer,
)

logger = logging.getLogger(__name__)

_CONTRACTOR_CREATE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["contractor_name"],
    properties={
        "contractor_name": openapi.Schema(type=openapi.TYPE_STRING, example="ABC Infra"),
        "contractor_code": openapi.Schema(type=openapi.TYPE_STRING, example="ABC001"),
        "contact_person": openapi.Schema(type=openapi.TYPE_STRING, example="John Smith"),
        "email": openapi.Schema(type=openapi.TYPE_STRING, example="john@abcinfra.com"),
        "phone": openapi.Schema(type=openapi.TYPE_STRING, example="9876543210"),
        "address": openapi.Schema(type=openapi.TYPE_STRING, example="Mumbai"),
    },
)

_CONTRACTOR_LIST_ITEM = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
        "contractor_name": openapi.Schema(type=openapi.TYPE_STRING, example="ABC Infra"),
        "contractor_code": openapi.Schema(type=openapi.TYPE_STRING, example="ABC001"),
        "status": openapi.Schema(type=openapi.TYPE_STRING, enum=["ACTIVE", "INACTIVE"], example="ACTIVE"),
    },
)


def _success(message: str, data, http_status=status.HTTP_200_OK):
    return Response({"success": True, "message": message, "data": data}, status=http_status)


def _error(message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
    payload = {"success": False, "message": message}
    if errors is not None:
        payload["errors"] = errors
    return Response(payload, status=http_status)


def _get_project_by_name(project_name: str) -> Project | None:
    return Project.objects.filter(name__iexact=project_name.strip()).first()


def _contractor_has_references(contractor: Contractor) -> bool:
    """Return True if contractor is linked in any PMC module."""
    if contractor.project_dates.exists():
        return True
    if contractor.contract_values.exists():
        return True
    if contractor.invoicing_records.exists():
        return True
    return False


class ContractorViewSet(viewsets.ViewSet):
    """Contractor Master CRUD scoped to projects."""

    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.GENERAL

    def get_rbac_project(self):
        """Resolve project from nested /projects/{project_name}/contractors/ routes."""
        project_name = self.kwargs.get("project_name")
        if project_name:
            return _get_project_by_name(project_name)

        pk = self.kwargs.get("pk")
        if pk:
            contractor = (
                Contractor.objects.select_related("project")
                .filter(pk=pk)
                .first()
            )
            if contractor is not None:
                return contractor.project
        return None

    @swagger_auto_schema(
        method="get",
        operation_summary="List contractors for a project",
        operation_description=(
            "Returns ACTIVE contractors by default. "
            "Use `?include_inactive=true` or `?status=INACTIVE` to include deactivated contractors."
        ),
        tags=["Contractors"],
        manual_parameters=[
            openapi.Parameter(
                "include_inactive",
                openapi.IN_QUERY,
                type=openapi.TYPE_BOOLEAN,
                required=False,
            ),
            openapi.Parameter(
                "status",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=["ACTIVE", "INACTIVE"],
                required=False,
            ),
        ],
        responses={200: openapi.Response("Contractors list", _CONTRACTOR_LIST_ITEM)},
    )
    @swagger_auto_schema(
        method="post",
        operation_summary="Create contractor",
        tags=["Contractors"],
        request_body=_CONTRACTOR_CREATE_SCHEMA,
    )
    @action(
        detail=False,
        methods=["get", "post"],
        url_path=r"projects/(?P<project_name>[^/.]+)/contractors",
    )
    def list_by_project(self, request, project_name=None):
        project = _get_project_by_name(project_name)
        if project is None:
            return _error(
                f"Project '{project_name}' not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            enforce_project_access(request.user, project)

            qs = Contractor.objects.filter(project=project).order_by("contractor_name")
            include_inactive = request.query_params.get("include_inactive", "").lower() in (
                "1",
                "true",
                "yes",
            )
            status_filter = request.query_params.get("status", "").upper()

            if status_filter in Contractor.Status.values:
                qs = qs.filter(status=status_filter)
            elif not include_inactive:
                qs = qs.filter(status=Contractor.Status.ACTIVE)

            data = ContractorListSerializer(qs, many=True).data
            return _success("Contractors retrieved successfully", data)

        enforce_project_write(request.user, project, RBACDomain.GENERAL)

        serializer = ContractorCreateSerializer(
            data=request.data,
            context={"project": project},
        )
        if not serializer.is_valid():
            return _error("Validation failed", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return _error("Validation failed", errors=exc.message_dict)

        return _success(
            "Contractor created successfully",
            ContractorSerializer(instance).data,
            http_status=status.HTTP_201_CREATED,
        )

    @swagger_auto_schema(
        operation_summary="Retrieve contractor by ID",
        tags=["Contractors"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"projects/contractors/(?P<pk>[^/.]+)",
    )
    def retrieve_contractor(self, request, pk=None):
        try:
            instance = Contractor.objects.select_related("project").get(pk=pk)
        except Contractor.DoesNotExist:
            return _error("Contractor not found", http_status=status.HTTP_404_NOT_FOUND)

        enforce_project_access(request.user, instance.project)
        return _success(
            "Contractor retrieved successfully",
            ContractorSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Update contractor",
        tags=["Contractors"],
    )
    @retrieve_contractor.mapping.patch
    def partial_update_contractor(self, request, pk=None):
        try:
            instance = Contractor.objects.select_related("project").get(pk=pk)
        except Contractor.DoesNotExist:
            return _error("Contractor not found", http_status=status.HTTP_404_NOT_FOUND)

        enforce_instance_write(request.user, instance, RBACDomain.GENERAL)

        serializer = ContractorUpdateSerializer(
            instance,
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return _error("Validation failed", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return _error("Validation failed", errors=exc.message_dict)

        return _success(
            "Contractor updated successfully",
            ContractorSerializer(instance).data,
        )

    @swagger_auto_schema(
        operation_summary="Delete or deactivate contractor",
        tags=["Contractors"],
    )
    @retrieve_contractor.mapping.delete
    def destroy_contractor(self, request, pk=None):
        try:
            instance = Contractor.objects.select_related("project").get(pk=pk)
        except Contractor.DoesNotExist:
            return _error("Contractor not found", http_status=status.HTTP_404_NOT_FOUND)

        enforce_instance_write(request.user, instance, RBACDomain.GENERAL)

        if _contractor_has_references(instance):
            instance.status = Contractor.Status.INACTIVE
            instance.save(update_fields=["status", "updated_at"])
            return _success(
                f"Contractor '{instance.contractor_name}' marked INACTIVE (linked records exist).",
                ContractorSerializer(instance).data,
            )

        instance.status = Contractor.Status.INACTIVE
        instance.save(update_fields=["status", "updated_at"])
        return _success(
            f"Contractor '{instance.contractor_name}' deactivated successfully.",
            {},
        )
