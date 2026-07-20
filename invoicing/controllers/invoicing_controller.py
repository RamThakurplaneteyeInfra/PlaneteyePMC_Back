"""
Invoicing Information Controller (ViewSet).

Handles all CRUD operations for InvoicingInformation records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Standard endpoints (via router):
  POST   /api/invoicing/                                          -> create
  GET    /api/invoicing/                                          -> list (all, filterable)
  GET    /api/invoicing/{id}/                                     -> retrieve by ID
  PUT    /api/invoicing/{id}/                                     -> full update
  PATCH  /api/invoicing/{id}/                                     -> partial update
  DELETE /api/invoicing/{id}/                                     -> destroy

Custom filter endpoints (via @action):
  GET    /api/invoicing/project/{projectName}/                    -> all types for a project
  GET    /api/invoicing/type/{invoiceType}/                       -> all projects for a type
  GET    /api/invoicing/project/{projectName}/type/{invoiceType}/ -> exact lookup

Auto-calculated fields (never send, always returned):
  - difference = gross_billed - gross_certified_billed
  - certification_efficiency = (gross_certified_billed / gross_billed) * 100

Scalable for future additions:
  - New invoice types: add to InvoicingInformation.InvoiceType enum only
  - Monthly invoicing tracking, payment history, collection analytics
  - Financial reporting and forecasting
"""

import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from core.cache_keys import build_rbac_list_cache_key, invalidate_list_cache

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, resolve_project
from accounts.rbac_checks import (
    apply_project_rbac_to_queryset,
    enforce_instance_write,
    enforce_project_access_by_name,
    enforce_project_write_by_name,
)

from contractors.resolvers import contractor_payload
from services.billing_update_notifications import (
    BillingAction,
    BillingModule,
    schedule_billing_update_notification,
    schedule_billing_update_notification_for_instance,
)

from ..models.invoicing_information import InvoicingInformation
from .invoicing_metrics import contractor_summary_from_records
from .invoicing_serializer import (
    InvoicingInformationSerializer,
    _normalize_invoice_type,
)

logger = logging.getLogger(__name__)

_STRIP_FIELDS = {
    "difference",
    "certification_efficiency",
    "netDue",
    "netBilledWithoutVAT",
    "netCollected",
    "id",
    "created_at",
    "updated_at",
}

_FIELD_ALIASES = {
    "projectName": "project_name",
    "invoiceType": "invoice_type",
    "contractorName": "contractor_name",
    "contractorId": "contractor_id",
    "grossBilled": "gross_billed",
    "grossCertifiedBilled": "gross_certified_billed",
    "netBilledWithoutVAT": "gross_billed",
    "netCollected": "gross_certified_billed",
}


def _normalise_payload(data: dict) -> dict:
    if hasattr(data, "copy"):
        data = data.copy()
    else:
        data = dict(data)

    normalised = {}
    for key, value in data.items():
        if key in _STRIP_FIELDS:
            continue
        canonical = _FIELD_ALIASES.get(key, key)
        normalised[canonical] = value

    if "invoice_type" in normalised:
        normalised["invoice_type"] = _normalize_invoice_type(
            str(normalised["invoice_type"])
        )
    if "project_name" in normalised and isinstance(normalised["project_name"], str):
        normalised["project_name"] = normalised["project_name"].strip()
    if "contractor_name" in normalised and isinstance(normalised["contractor_name"], str):
        normalised["contractor_name"] = normalised["contractor_name"].strip()

    return normalised


def _find_existing_record(
    project_name: str,
    invoice_type: str,
    contractor_id: int | None = None,
    contractor_name: str | None = None,
):
    """Locate an existing record for upsert (SCL or named contractor)."""
    if not project_name or not invoice_type:
        return None

    filters = {
        "project_name__iexact": project_name.strip(),
        "invoice_type": invoice_type,
    }
    if invoice_type == InvoicingInformation.InvoiceType.CONTRACTOR:
        if contractor_id:
            filters["contractor_id"] = contractor_id
        else:
            name = (contractor_name or "").strip()
            if not name:
                return None
            filters["contractor_name__iexact"] = name

    try:
        return InvoicingInformation.objects.get(**filters)
    except InvoicingInformation.DoesNotExist:
        return None


def _build_project_payload(project_name: str, records) -> dict:
    """Shape GET-by-project response with scl, contractors[], and deprecated contractor."""
    scl_record = None
    contractor_records = []
    for record in records:
        if record.invoice_type == InvoicingInformation.InvoiceType.SCL:
            scl_record = record
        else:
            contractor_records.append(record)

    contractors_data = [
        {
            "id": record.id,
            "contractor_name": record.contractor_name,
            "contractor": contractor_payload(record.contractor),
            "invoicing": InvoicingInformationSerializer(record).data,
        }
        for record in contractor_records
    ]

    first_contractor_invoicing = (
        contractors_data[0]["invoicing"] if contractors_data else None
    )

    return {
        "project_name": project_name,
        "scl": InvoicingInformationSerializer(scl_record).data if scl_record else None,
        "contractor_summary": contractor_summary_from_records(contractor_records),
        "contractors": contractors_data,
        "contractor": first_contractor_invoicing,
    }

# Cache settings
_CACHE_KEY_LIST = "invoicing_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class InvoicingPagination(PageNumberPagination):
    """Standard pagination for invoicing records (20/page, configurable)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_INV_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "invoice_type"],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Thane Project",
        ),
        "invoice_type": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='Invoice type: "SCL" or "CONTRACTOR"',
            enum=["SCL", "CONTRACTOR"],
            example="SCL",
        ),
        "contractor_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Required when invoice_type=CONTRACTOR. Omit for SCL.",
            example="ABC Infra",
        ),
        "gross_billed": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Gross billed amount (>= 0)",
            example=120000000.00,
        ),
        "gross_certified_billed": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Gross certified billed amount (>= 0)",
            example=100000000.00,
        ),
    },
)

_INV_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Invoice record created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "project_name": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Thane Project"
                ),
                "invoice_type": openapi.Schema(
                    type=openapi.TYPE_STRING, example="SCL"
                ),
                "gross_billed": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=120000000.00
                ),
                "gross_certified_billed": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=100000000.00
                ),
                "difference": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="gross_billed - gross_certified_billed",
                    example=20000000.00,
                ),
                "certification_efficiency": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="(gross_certified_billed / gross_billed) * 100",
                    example=83.33,
                ),
                "created_at": openapi.Schema(
                    type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"
                ),
                "updated_at": openapi.Schema(
                    type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"
                ),
            },
        ),
    },
)


# =============================================================================
# Reusable utility functions
# =============================================================================

def _build_queryset(
    project_name: str = None,
    invoice_type: str = None,
    contractor_name: str = None,
    search: str = None,
):
    """
    Reusable queryset builder with optional filters.
    Used by list, project lookup, type lookup, and combined lookup.

    Args:
        project_name : partial, case-insensitive project name filter
        invoice_type : exact invoice type filter (SCL | CONTRACTOR; legacy PMC/Contractor accepted)
        search       : free-text search across project_name
    """
    qs = InvoicingInformation.objects.only(
        "id",
        "project_name",
        "invoice_type",
        "contractor_name",
        "gross_billed",
        "gross_certified_billed",
        "created_at",
        "updated_at",
    )

    if project_name:
        qs = qs.filter(project_name__icontains=project_name.strip())

    if invoice_type:
        qs = qs.filter(
            invoice_type=_normalize_invoice_type(invoice_type.strip())
        )

    if contractor_name:
        qs = qs.filter(contractor_name__iexact=contractor_name.strip())

    if search:
        qs = qs.filter(project_name__icontains=search.strip())

    return qs


def _cache_key_for_filters(
    request, project_name=None, invoice_type=None, page="1"
) -> str:
    """Generate a deterministic RBAC-aware cache key from active filters."""
    parts = []
    if project_name:
        parts.append(f"p:{project_name.strip().lower()}")
    if invoice_type:
        parts.append(f"t:{invoice_type.strip()}")
    parts.append(f"pg:{page}")
    return build_rbac_list_cache_key(
        _CACHE_KEY_LIST,
        request,
        extra_parts=parts,
        use_query_string=False,
    )


# =============================================================================
# ViewSet
# =============================================================================

class InvoicingInformationViewSet(viewsets.ModelViewSet):
    """
    Invoicing Information ViewSet.

    Manages invoicing KPIs per project per invoice type.
    One SCL record per project; multiple CONTRACTOR records (unique contractor_name).

    The invoice_type field acts as a discriminator — the same API serves
    both SCL and CONTRACTOR invoicing data.

    Calculated fields (difference, certification_efficiency) are computed at read time.
    Clients send: project_name, invoice_type, gross_billed, gross_certified_billed.
    """

    queryset = InvoicingInformation.objects.all()
    serializer_class = InvoicingInformationSerializer
    pagination_class = InvoicingPagination
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.BILLING

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset with optional query-param filters.

        Supported query params:
          ?project_name=  — partial, case-insensitive project name filter
          ?invoice_type=  — exact invoice type filter (SCL | CONTRACTOR)
          ?search=        — free-text search across project_name
        """
        qs = _build_queryset(
            project_name=self.request.query_params.get("project_name"),
            invoice_type=self.request.query_params.get("invoice_type"),
            search=self.request.query_params.get("search"),
        )
        return apply_project_rbac_to_queryset(qs, self.request, "project_name")

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate all invoicing list caches on any write."""
        invalidate_list_cache(_CACHE_KEY_LIST)

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        """Uniform success response: {success, message, data}."""
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(
        self,
        message: str,
        errors=None,
        http_status=status.HTTP_400_BAD_REQUEST,
    ):
        """Uniform error response: {success, message, errors?}."""
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    def _paginated_success(self, request, queryset, message: str):
        """
        Reusable helper: paginate a queryset and wrap in success envelope.
        Used by list, project lookup, type lookup, and combined lookup.
        """
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = InvoicingInformationSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": message,
                    "data": paginated.data,
                }
            )
        serializer = InvoicingInformationSerializer(queryset, many=True)
        return Response(
            {"success": True, "message": message, "data": serializer.data}
        )

    # -------------------------------------------------------------------------
    # CREATE  POST /api/invoicing/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Invoice Record",
        operation_description=(
            "Create or update an invoicing record.\n\n"
            "**SCL:** one record per project (`contractor_name` omitted).\n"
            "**CONTRACTOR:** upserts by `(project_name, contractor_name)` — "
            "each contractor maintains independent invoicing data.\n\n"
            "**Auto-calculated (do not send):**\n"
            "- `difference` = gross_billed − gross_certified_billed\n"
            "- `certification_efficiency` = (gross_certified_billed / gross_billed) × 100"
        ),
        request_body=_INV_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _INV_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Invoicing"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update an invoicing record.

        SCL upserts by (project_name, invoice_type).
        CONTRACTOR upserts by (project_name, invoice_type, contractor_name).
        """
        payload = _normalise_payload(request.data)
        project_name = str(payload.get("project_name", "")).strip()
        enforce_project_write_by_name(
            request.user, project_name, RBACDomain.BILLING
        )
        invoice_type = payload.get("invoice_type", "")
        contractor_id = payload.get("contractor_id")
        contractor_name = payload.get("contractor_name")

        existing = _find_existing_record(
            project_name, invoice_type, contractor_id, contractor_name
        )

        if existing is not None:
            serializer = InvoicingInformationSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = InvoicingInformationSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"InvoicingInformation create error: {exc}")
            return self._error(
                "Failed to save invoice record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        action = BillingAction.UPDATE if existing else BillingAction.CREATE
        schedule_billing_update_notification(
            request.user,
            resolve_project(project_name),
            BillingModule.INVOICING,
            action,
        )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Invoice record updated successfully"
            if existing
            else "Invoice record created successfully"
        )

        return self._success(
            message,
            InvoicingInformationSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/invoicing/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Invoice Records",
        operation_description=(
            "Retrieve all invoicing records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?invoice_type=SCL` or `?invoice_type=CONTRACTOR`\n"
            "- `?search=` — free-text search across project names\n"
            "- Combine: `?project_name=Smart City&invoice_type=PMC`"
        ),
        manual_parameters=[
            openapi.Parameter(
                "project_name", openapi.IN_QUERY,
                description="Filter by project name (partial, case-insensitive)",
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "invoice_type", openapi.IN_QUERY,
                description='Filter by invoice type: "SCL" or "CONTRACTOR"',
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "search", openapi.IN_QUERY,
                description="Free-text search across project names",
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "page", openapi.IN_QUERY,
                description="Page number",
                type=openapi.TYPE_INTEGER, required=False,
            ),
            openapi.Parameter(
                "page_size", openapi.IN_QUERY,
                description="Records per page (max 100)",
                type=openapi.TYPE_INTEGER, required=False,
            ),
        ],
        responses={200: openapi.Response("OK", _INV_RESPONSE_SCHEMA)},
        tags=["Invoicing"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all invoicing records (paginated, filterable).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        type_filter = request.query_params.get("invoice_type")
        search_filter = request.query_params.get("search")
        page_param = request.query_params.get("page", "1")

        use_cache = (
            not any([project_filter, type_filter, search_filter])
            and page_param == "1"
        )
        cache_key = _cache_key_for_filters(
            request, project_filter, type_filter, page_param
        )

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = InvoicingInformationSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Invoice records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(cache_key, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = InvoicingInformationSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Invoice records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(cache_key, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/invoicing/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Invoice Record by ID",
        responses={
            200: openapi.Response("OK", _INV_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single invoicing record by its primary key."""
        try:
            instance = InvoicingInformation.objects.get(pk=kwargs["pk"])
        except InvoicingInformation.DoesNotExist:
            return self._error(
                "Invoice record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Invoice record retrieved successfully",
            InvoicingInformationSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/invoicing/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Invoice Record",
        operation_description=(
            "Full or partial update of an invoicing record. "
            "difference and certification_efficiency are returned on every update."
        ),
        request_body=_INV_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _INV_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of an invoicing record.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = InvoicingInformation.objects.get(pk=kwargs["pk"])
        except InvoicingInformation.DoesNotExist:
            return self._error(
                "Invoice record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.BILLING)

        payload = _normalise_payload(request.data)

        serializer = InvoicingInformationSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"InvoicingInformation update error: {exc}")
            return self._error(
                "Failed to update invoice record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_billing_update_notification_for_instance(
            request.user,
            updated,
            BillingModule.INVOICING,
            BillingAction.UPDATE,
        )

        self._invalidate_cache()

        return self._success(
            "Invoice record updated successfully",
            InvoicingInformationSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/invoicing/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Invoice Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete an invoicing record by its primary key."""
        try:
            instance = InvoicingInformation.objects.get(pk=kwargs["pk"])
        except InvoicingInformation.DoesNotExist:
            return self._error(
                "Invoice record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        enforce_instance_write(request.user, instance, RBACDomain.BILLING)

        project_name = instance.project_name
        invoice_type = instance.invoice_type
        contractor_label = (
            f" — {instance.contractor_name}" if instance.contractor_name else ""
        )
        schedule_billing_update_notification(
            request.user,
            resolve_project(project_name),
            BillingModule.INVOICING,
            BillingAction.DELETE,
        )
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"Invoice record for '{project_name}' [{invoice_type}{contractor_label}] deleted successfully",
            {},
        )

    # =========================================================================
    # CUSTOM FILTER ACTIONS
    # =========================================================================

    # -------------------------------------------------------------------------
    # GET /api/invoicing/project/{projectName}/
    # Returns ALL invoice types for a given project (SCL + CONTRACTOR)
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Invoice Records by Project Name",
        operation_description=(
            "Retrieve SCL and all contractor invoicing records for a project.\n\n"
            "Returns `contractors` as an array (one entry per contractor), "
            "`contractor_summary` with backend-calculated cumulative totals, "
            "and `contractor` for backward compatibility (first contractor)."
        ),
        responses={
            200: openapi.Response(
                "OK",
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                        "data": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "project_name": openapi.Schema(type=openapi.TYPE_STRING),
                                "scl": openapi.Schema(type=openapi.TYPE_OBJECT, nullable=True),
                                "contractor_summary": openapi.Schema(
                                    type=openapi.TYPE_OBJECT,
                                    description="Cumulative totals across all contractors",
                                ),
                                "contractors": openapi.Schema(
                                    type=openapi.TYPE_ARRAY,
                                    items=openapi.Schema(type=openapi.TYPE_OBJECT),
                                ),
                                "contractor": openapi.Schema(
                                    type=openapi.TYPE_OBJECT,
                                    nullable=True,
                                    description="Deprecated — first contractor invoicing",
                                ),
                            },
                        ),
                    },
                ),
            ),
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Return SCL and all contractor invoicing records for a project.

        Response includes:
          - scl: single SCL record or null
          - contractor_summary: cumulative totals across all contractors
          - contractors: array with id, contractor_name, invoicing
          - contractor: first contractor's invoicing (backward compatibility)
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        project_name = projectName.strip()
        enforce_project_access_by_name(request.user, project_name)

        qs = apply_project_rbac_to_queryset(
            _build_queryset(project_name=project_name),
            request,
            "project_name",
        ).order_by("invoice_type", "contractor_name")

        if not qs.exists():
            return self._error(
                f"No invoice records found for project '{project_name}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        actual_name = qs.first().project_name
        payload = _build_project_payload(actual_name, qs)

        return self._success(
            f"Invoice records for project '{actual_name}' retrieved successfully",
            payload,
        )

    # -------------------------------------------------------------------------
    # GET /api/invoicing/type/{invoiceType}/
    # Returns all projects for a given invoice type
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Invoice Records by Invoice Type",
        operation_description=(
            "Retrieve all records for a specific invoice type across all projects.\n\n"
            "Valid values: `SCL`, `CONTRACTOR` (legacy `PMC` / `Contractor` accepted)\n\n"
            "Useful for type-wise analytics and dashboard filtering."
        ),
        responses={
            200: openapi.Response("OK", _INV_RESPONSE_SCHEMA),
            400: "Invalid invoice type",
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"type/(?P<invoiceType>[^/.]+)",
        url_name="by-invoice-type",
    )
    def get_by_invoice_type(self, request, invoiceType: str = None):
        """
        Retrieve all invoicing records for a specific invoice type.
        Supports all projects filtered by SCL or CONTRACTOR.
        """
        if not invoiceType or not invoiceType.strip():
            return self._error("invoiceType is required.")

        normalized = _normalize_invoice_type(invoiceType.strip())
        valid_types = [c.value for c in InvoicingInformation.InvoiceType]
        if normalized not in valid_types:
            return self._error(
                f"Invalid invoiceType '{invoiceType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        qs = apply_project_rbac_to_queryset(
            _build_queryset(invoice_type=normalized),
            request,
            "project_name",
        )

        if not qs.exists():
            return self._error(
                f"No invoice records found for invoiceType '{invoiceType}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._paginated_success(
            request, qs,
            f"Invoice records for type '{invoiceType.strip()}' retrieved successfully",
        )

    # -------------------------------------------------------------------------
    # GET /api/invoicing/project/{projectName}/type/{invoiceType}/
    # Exact lookup: one specific record
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Invoice Record by Project Name and Invoice Type",
        operation_description=(
            "Retrieve the invoicing record for a specific project + type.\n\n"
            "For CONTRACTOR type, pass `?contractor_name=` when multiple contractors exist.\n\n"
            "**Examples:**\n"
            "- `GET /api/invoicing/project/Thane Project/type/SCL/`\n"
            "- `GET /api/invoicing/project/Thane Project/type/CONTRACTOR/?contractor_name=ABC Infra`"
        ),
        manual_parameters=[
            openapi.Parameter(
                "contractor_name",
                openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description="Required when multiple CONTRACTOR records exist for the project.",
            ),
        ],
        responses={
            200: openapi.Response("OK", _INV_RESPONSE_SCHEMA),
            400: "Invalid invoice type or missing contractor_name",
            404: "Not found",
        },
        tags=["Invoicing"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/type/(?P<invoiceType>[^/.]+)",
        url_name="by-project-and-type",
    )
    def get_by_project_and_type(
        self, request, projectName: str = None, invoiceType: str = None
    ):
        """
        Retrieve the exact invoicing record for a (projectName, invoiceType) pair.
        Case-insensitive project name lookup.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")
        if not invoiceType or not invoiceType.strip():
            return self._error("invoiceType is required.")

        normalized = _normalize_invoice_type(invoiceType.strip())
        valid_types = [c.value for c in InvoicingInformation.InvoiceType]
        if normalized not in valid_types:
            return self._error(
                f"Invalid invoiceType '{invoiceType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        enforce_project_access_by_name(request.user, projectName.strip())

        project_name = projectName.strip()
        contractor_name = (request.query_params.get("contractor_name") or "").strip()
        contractor_id = request.query_params.get("contractor_id")

        if normalized == InvoicingInformation.InvoiceType.SCL:
            try:
                instance = InvoicingInformation.objects.get(
                    project_name__iexact=project_name,
                    invoice_type=normalized,
                )
            except InvoicingInformation.DoesNotExist:
                return self._error(
                    f"No invoice record found for project '{projectName}' "
                    f"with invoiceType '{invoiceType}'",
                    http_status=status.HTTP_404_NOT_FOUND,
                )
        else:
            contractor_qs = InvoicingInformation.objects.filter(
                project_name__iexact=project_name,
                invoice_type=normalized,
            )
            if not contractor_qs.exists():
                return self._error(
                    f"No invoice record found for project '{projectName}' "
                    f"with invoiceType '{invoiceType}'",
                    http_status=status.HTTP_404_NOT_FOUND,
                )

            if contractor_id or contractor_name:
                try:
                    if contractor_id:
                        instance = contractor_qs.get(contractor_id=int(contractor_id))
                    else:
                        instance = contractor_qs.get(
                            contractor_name__iexact=contractor_name,
                        )
                except (InvoicingInformation.DoesNotExist, ValueError):
                    label = contractor_id or contractor_name
                    return self._error(
                        f"No invoice record found for contractor '{label}' "
                        f"on project '{projectName}'",
                        http_status=status.HTTP_404_NOT_FOUND,
                    )
            elif contractor_qs.count() == 1:
                instance = contractor_qs.first()
            else:
                return self._error(
                    "Multiple contractors exist for this project. "
                    "Pass ?contractor_id= or ?contractor_name= to select one.",
                    http_status=status.HTTP_400_BAD_REQUEST,
                )

        return self._success(
            f"Invoice record for '{project_name}' [{invoiceType.strip()}] "
            "retrieved successfully",
            InvoicingInformationSerializer(instance).data,
        )
