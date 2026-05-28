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

Auto-calculated field (never send, always returned):
  - netDue = netBilledWithoutVAT - netCollected

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
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models.invoicing_information import InvoicingInformation
from .invoicing_serializer import InvoicingInformationSerializer

logger = logging.getLogger(__name__)

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
    required=["projectName", "invoiceType"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="PMC Smart City",
        ),
        "invoiceType": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='Invoice type: "PMC" or "Contractor"',
            enum=["PMC", "Contractor"],
            example="PMC",
        ),
        "grossBilled": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Total amount billed including VAT (>= 0)",
            example=120000000.00,
        ),
        "netBilledWithoutVAT": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Net amount billed excluding VAT (>= 0)",
            example=100000000.00,
        ),
        "netCollected": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description=(
                "Amount actually collected "
                "(>= 0, cannot exceed netBilledWithoutVAT)"
            ),
            example=80000000.00,
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
                "projectName": openapi.Schema(
                    type=openapi.TYPE_STRING, example="PMC Smart City"
                ),
                "invoiceType": openapi.Schema(
                    type=openapi.TYPE_STRING, example="PMC"
                ),
                "grossBilled": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=120000000.00
                ),
                "netBilledWithoutVAT": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=100000000.00
                ),
                "netCollected": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=80000000.00
                ),
                "netDue": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Auto-calculated: netBilledWithoutVAT - netCollected",
                    example=20000000.00,
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
    search: str = None,
):
    """
    Reusable queryset builder with optional filters.
    Used by list, project lookup, type lookup, and combined lookup.

    Args:
        project_name : partial, case-insensitive project name filter
        invoice_type : exact invoice type filter (PMC | Contractor)
        search       : free-text search across projectName
    """
    qs = InvoicingInformation.objects.only(
        "id",
        "projectName",
        "invoiceType",
        "grossBilled",
        "netBilledWithoutVAT",
        "netCollected",
        "netDue",
        "created_at",
        "updated_at",
    )

    if project_name:
        qs = qs.filter(projectName__icontains=project_name.strip())

    if invoice_type:
        qs = qs.filter(invoiceType=invoice_type.strip())

    if search:
        qs = qs.filter(projectName__icontains=search.strip())

    return qs


def _cache_key_for_filters(
    project_name=None, invoice_type=None, page="1"
) -> str:
    """Generate a deterministic cache key from active filters."""
    parts = []
    if project_name:
        parts.append(f"p:{project_name.strip().lower()}")
    if invoice_type:
        parts.append(f"t:{invoice_type.strip()}")
    parts.append(f"pg:{page}")
    return f"{_CACHE_KEY_LIST}:{':'.join(parts) if parts else 'all'}"


# =============================================================================
# ViewSet
# =============================================================================

class InvoicingInformationViewSet(viewsets.ModelViewSet):
    """
    Invoicing Information ViewSet.

    Manages invoicing KPIs per project per invoice type.
    One record per (projectName, invoiceType) pair.

    The invoiceType field acts as a discriminator — the same API serves
    both PMC and Contractor invoicing data. New types can be added to
    the enum without any structural changes.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send: projectName, invoiceType, and the input values.
    """

    queryset = InvoicingInformation.objects.all()
    serializer_class = InvoicingInformationSerializer
    permission_classes = [AllowAny]
    pagination_class = InvoicingPagination

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset with optional query-param filters.

        Supported query params:
          ?project_name=  — partial, case-insensitive project name filter
          ?invoice_type=  — exact invoice type filter (PMC | Contractor)
          ?search=        — free-text search across projectName
        """
        return _build_queryset(
            project_name=self.request.query_params.get("project_name"),
            invoice_type=self.request.query_params.get("invoice_type"),
            search=self.request.query_params.get("search"),
        )

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate all invoicing list caches on any write."""
        try:
            if hasattr(cache, "delete_pattern"):
                cache.delete_pattern(f"{_CACHE_KEY_LIST}:*")
            else:
                cache.delete(_CACHE_KEY_LIST)
        except Exception:
            try:
                cache.clear()
            except Exception:
                pass

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
            "Create a new invoicing record for a project and invoice type.\n\n"
            "**One record per (projectName, invoiceType) pair.**\n\n"
            "**Auto-calculated field (do not send):**\n"
            "- `netDue` = netBilledWithoutVAT − netCollected\n\n"
            "**Constraint:** netCollected cannot exceed netBilledWithoutVAT.\n\n"
            "**Example — create both types for the same project:**\n"
            "```\n"
            'POST { "projectName": "PMC Smart City", "invoiceType": "PMC", ... }\n'
            'POST { "projectName": "PMC Smart City", "invoiceType": "Contractor", ... }\n'
            "```"
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
        Create or update an invoicing record (upsert by projectName + invoiceType).

        If a record already exists for the given (projectName, invoiceType) pair
        it is updated in-place rather than returning a 400/500 uniqueness error.
        This matches the expected dashboard behaviour where the frontend always
        POSTs the latest values for a project.

        Auto-calculates netDue = netBilledWithoutVAT - netCollected.
        """
        project_name = str(request.data.get("projectName", "")).strip()
        invoice_type = str(request.data.get("invoiceType", "")).strip()

        # Strip read-only / auto-calculated fields the frontend should not send
        _READ_ONLY = {"netDue", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        # ------------------------------------------------------------------
        # Upsert: if a record already exists for this pair, update it.
        # ------------------------------------------------------------------
        existing = None
        if project_name and invoice_type:
            try:
                existing = InvoicingInformation.objects.get(
                    projectName__iexact=project_name,
                    invoiceType=invoice_type,
                )
            except InvoicingInformation.DoesNotExist:
                pass

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
            "- `?invoice_type=PMC` or `?invoice_type=Contractor`\n"
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
                description='Filter by invoice type: "PMC" or "Contractor"',
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
        cache_key = _cache_key_for_filters(project_filter, type_filter, page_param)

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
            "netDue is recalculated automatically after every update."
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
        netDue is recomputed after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = InvoicingInformation.objects.get(pk=kwargs["pk"])
        except InvoicingInformation.DoesNotExist:
            return self._error(
                "Invoice record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        _READ_ONLY = {"netDue", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

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

        project_name = instance.projectName
        invoice_type = instance.invoiceType
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"Invoice record for '{project_name}' [{invoice_type}] deleted successfully",
            {},
        )

    # =========================================================================
    # CUSTOM FILTER ACTIONS
    # =========================================================================

    # -------------------------------------------------------------------------
    # GET /api/invoicing/project/{projectName}/
    # Returns ALL invoice types for a given project (PMC + Contractor)
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Invoice Records by Project Name",
        operation_description=(
            "Retrieve all invoice type records for a given project.\n\n"
            "Returns both PMC and Contractor records (if they exist).\n"
            "Useful for dashboard invoicing comparison tables."
        ),
        responses={
            200: openapi.Response("OK", _INV_RESPONSE_SCHEMA),
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
        Retrieve all invoicing records for a project (all types).
        Returns both PMC and Contractor records for the same project.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        qs = _build_queryset(project_name=projectName)

        if not qs.exists():
            return self._error(
                f"No invoice records found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._paginated_success(
            request, qs,
            f"Invoice records for project '{projectName.strip()}' retrieved successfully",
        )

    # -------------------------------------------------------------------------
    # GET /api/invoicing/type/{invoiceType}/
    # Returns all projects for a given invoice type
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Invoice Records by Invoice Type",
        operation_description=(
            "Retrieve all records for a specific invoice type across all projects.\n\n"
            "Valid values: `PMC`, `Contractor`\n\n"
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
        Supports all projects filtered by PMC or Contractor.
        """
        if not invoiceType or not invoiceType.strip():
            return self._error("invoiceType is required.")

        valid_types = [c.value for c in InvoicingInformation.InvoiceType]
        if invoiceType.strip() not in valid_types:
            return self._error(
                f"Invalid invoiceType '{invoiceType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        qs = _build_queryset(invoice_type=invoiceType.strip())

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
            "Retrieve the exact invoicing record for a specific project + type.\n\n"
            "**Examples:**\n"
            "- `GET /api/invoicing/project/PMC Smart City/type/PMC/`\n"
            "- `GET /api/invoicing/project/PMC Smart City/type/Contractor/`\n\n"
            "Ideal for dashboard KPI cards that display PMC and Contractor "
            "invoicing side-by-side."
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

        valid_types = [c.value for c in InvoicingInformation.InvoiceType]
        if invoiceType.strip() not in valid_types:
            return self._error(
                f"Invalid invoiceType '{invoiceType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        try:
            instance = InvoicingInformation.objects.get(
                projectName__iexact=projectName.strip(),
                invoiceType=invoiceType.strip(),
            )
        except InvoicingInformation.DoesNotExist:
            return self._error(
                f"No invoice record found for project '{projectName}' "
                f"with invoiceType '{invoiceType}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            f"Invoice record for '{projectName.strip()}' [{invoiceType.strip()}] "
            "retrieved successfully",
            InvoicingInformationSerializer(instance).data,
        )
