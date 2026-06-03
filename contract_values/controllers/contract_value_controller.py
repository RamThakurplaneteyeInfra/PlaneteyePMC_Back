"""
Contract Value Controller (ViewSet).

Handles all CRUD operations for ContractValue records.
Uses DRF ModelViewSet with a uniform {success, message, data} response envelope.

Standard endpoints (via router):
  POST   /api/contract-values/                                    -> create
  GET    /api/contract-values/                                    -> list (all, filterable)
  GET    /api/contract-values/{id}/                               -> retrieve by ID
  PUT    /api/contract-values/{id}/                               -> full update
  PATCH  /api/contract-values/{id}/                               -> partial update
  DELETE /api/contract-values/{id}/                               -> destroy

Custom filter endpoints (via @action):
  GET    /api/contract-values/project/{projectName}/              -> all types for a project
  GET    /api/contract-values/type/{contractType}/                -> all projects for a type
  GET    /api/contract-values/project/{projectName}/type/{contractType}/  -> exact lookup

Auto-calculated fields (never send, always returned):
  - revised_value         = original_contract_value + excess_value - saving
  - increase_percentage   = ((revised_value - original_contract_value) / original_contract_value) * 100

Scalable for future additions:
  - New contract types: add to ContractValue.ContractType enum only
  - Monthly tracking, baseline comparison, forecasting
  - Contract health indicators and analytics
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

from ..models.contract_value import ContractValue
from .contract_value_serializer import ContractValueSerializer, _normalize_contract_type

logger = logging.getLogger(__name__)

_STRIP_FIELDS = {
    "revised_value",
    "increase_percentage",
    "revisedContractValue",
    "approvedVOPercentage",
    "approvedVO",
    "potentialPendingVO",
    "id",
    "created_at",
    "updated_at",
}

_FIELD_ALIASES = {
    "projectName": "project_name",
    "contractType": "contract_type",
    "originalContractValue": "original_contract_value",
    "excessValue": "excess_value",
    "approvedVO": "excess_value",
    "potentialPendingVO": "saving",
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

    if "contract_type" in normalised:
        normalised["contract_type"] = _normalize_contract_type(
            str(normalised["contract_type"])
        )
    if "project_name" in normalised and isinstance(normalised["project_name"], str):
        normalised["project_name"] = normalised["project_name"].strip()

    return normalised

# Cache settings
_CACHE_KEY_LIST = "contract_values_list"
_CACHE_TIMEOUT = 300  # 5 minutes


# =============================================================================
# Pagination
# =============================================================================

class ContractValuePagination(PageNumberPagination):
    """Standard pagination for contract value records (20/page, configurable)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# Swagger schema helpers
# =============================================================================

_CV_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["project_name", "contract_type"],
    properties={
        "project_name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Project name",
            example="Thane Project",
        ),
        "contract_type": openapi.Schema(
            type=openapi.TYPE_STRING,
            description='Contract type: "SCL" or "CONTRACTOR"',
            enum=["SCL", "CONTRACTOR"],
            example="SCL",
        ),
        "original_contract_value": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Original contract value (>= 0)",
            example=10000000.00,
        ),
        "excess_value": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Excess value (>= 0)",
            example=500000.00,
        ),
        "saving": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Saving amount (>= 0)",
            example=250000.00,
        ),
    },
)

_CV_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            example="Contract value record created successfully",
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "project_name": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Thane Project"
                ),
                "contract_type": openapi.Schema(
                    type=openapi.TYPE_STRING, example="SCL"
                ),
                "original_contract_value": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=10000000.00
                ),
                "excess_value": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=500000.00
                ),
                "saving": openapi.Schema(
                    type=openapi.TYPE_NUMBER, example=250000.00
                ),
                "revised_value": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="original_contract_value + excess_value - saving",
                    example=10250000.00,
                ),
                "increase_percentage": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="((revised_value - original) / original) * 100",
                    example=2.50,
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
    contract_type: str = None,
    search: str = None,
):
    """
    Reusable queryset builder with optional filters.
    Used by list, project lookup, type lookup, and combined lookup.

    Args:
        project_name : exact or partial project name filter
        contract_type: exact contract type filter (SCL | Contractor)
        search       : free-text search across projectName
    """
    qs = ContractValue.objects.only(
        "id",
        "project_name",
        "contract_type",
        "original_contract_value",
        "excess_value",
        "saving",
        "created_at",
        "updated_at",
    )

    if project_name:
        qs = qs.filter(project_name__icontains=project_name.strip())

    if contract_type:
        qs = qs.filter(contract_type=_normalize_contract_type(contract_type.strip()))

    if search:
        qs = qs.filter(project_name__icontains=search.strip())

    return qs


def _cache_key_for_filters(project_name=None, contract_type=None, page="1"):
    """Generate a deterministic cache key from active filters."""
    parts = []
    if project_name:
        parts.append(f"p:{project_name.strip().lower()}")
    if contract_type:
        parts.append(f"t:{contract_type.strip()}")
    parts.append(f"pg:{page}")
    return f"{_CACHE_KEY_LIST}:{':'.join(parts) if parts else 'all'}"


# =============================================================================
# ViewSet
# =============================================================================

class ContractValueViewSet(viewsets.ModelViewSet):
    """
    Contract Value ViewSet.

    Manages contract financial KPIs per project per contract type.
    One record per (projectName, contractType) pair.

    The contractType field acts as a discriminator — the same API serves
    both SCL and Contractor data. New types can be added to the enum
    without any structural changes.

    All calculated fields are auto-computed by the model on every save.
    Clients only need to send: projectName, contractType, and the input values.
    """

    queryset = ContractValue.objects.all()
    serializer_class = ContractValueSerializer
    permission_classes = [AllowAny]
    pagination_class = ContractValuePagination

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Return optimised queryset with optional query-param filters.

        Supported query params:
          ?project_name=   — partial, case-insensitive project name filter
          ?contract_type=  — exact contract type filter (SCL | Contractor)
          ?search=         — free-text search across projectName
        """
        return _build_queryset(
            project_name=self.request.query_params.get("project_name"),
            contract_type=self.request.query_params.get("contract_type"),
            search=self.request.query_params.get("search"),
        )

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate all contract value list caches on any write."""
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
            serializer = ContractValueSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            return Response(
                {
                    "success": True,
                    "message": message,
                    "data": paginated.data,
                }
            )
        serializer = ContractValueSerializer(queryset, many=True)
        return Response(
            {"success": True, "message": message, "data": serializer.data}
        )

    # -------------------------------------------------------------------------
    # CREATE  POST /api/contract-values/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create Contract Value Record",
        operation_description=(
            "Create a new contract value record for a project and contract type.\n\n"
            "**One record per (projectName, contractType) pair.**\n\n"
            "**Auto-calculated fields (do not send):**\n"
            "- `revised_value` = original_contract_value + excess_value - saving\n"
            "- `increase_percentage` = ((revised_value - original_contract_value) / original_contract_value) × 100\n\n"
            "**Example — create both types for the same project:**\n"
            "```\n"
            'POST { "projectName": "PMC Smart City", "contractType": "SCL", ... }\n'
            'POST { "projectName": "PMC Smart City", "contractType": "Contractor", ... }\n'
            "```"
        ),
        request_body=_CV_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _CV_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["Contract Values"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a contract value record (upsert by projectName + contractType).

        If a record already exists for the given (projectName, contractType) pair
        it is updated in-place rather than returning a 400/500 uniqueness error.

        Computed fields are stripped from the payload before validation.
        """
        payload = _normalise_payload(request.data)
        project_name = payload.get("project_name", "")
        contract_type = payload.get("contract_type", "")

        existing = None
        if project_name and contract_type:
            try:
                existing = ContractValue.objects.get(
                    project_name__iexact=project_name,
                    contract_type=contract_type,
                )
            except ContractValue.DoesNotExist:
                pass

        if existing is not None:
            serializer = ContractValueSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = ContractValueSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ContractValue create error: {exc}", exc_info=True)
            return self._error(
                "Failed to save contract value record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "Contract value record updated successfully"
            if existing
            else "Contract value record created successfully"
        )

        return self._success(
            message,
            ContractValueSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/contract-values/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Contract Value Records",
        operation_description=(
            "Retrieve all contract value records.\n\n"
            "**Supports filtering:**\n"
            "- `?project_name=` — partial, case-insensitive project name\n"
            "- `?contract_type=SCL` or `?contract_type=CONTRACTOR`\n"
            "- `?search=` — free-text search across project names\n"
            "- Combine: `?project_name=Smart City&contract_type=SCL`"
        ),
        manual_parameters=[
            openapi.Parameter(
                "project_name", openapi.IN_QUERY,
                description="Filter by project name (partial, case-insensitive)",
                type=openapi.TYPE_STRING, required=False,
            ),
            openapi.Parameter(
                "contract_type", openapi.IN_QUERY,
                description='Filter by contract type: "SCL" or "CONTRACTOR"',
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
        responses={200: openapi.Response("OK", _CV_RESPONSE_SCHEMA)},
        tags=["Contract Values"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all contract value records (paginated, filterable).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        type_filter = request.query_params.get("contract_type")
        search_filter = request.query_params.get("search")
        page_param = request.query_params.get("page", "1")

        # Only cache unfiltered first-page requests
        use_cache = not any([project_filter, type_filter, search_filter]) and page_param == "1"
        cache_key = _cache_key_for_filters(project_filter, type_filter, page_param)

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = ContractValueSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "Contract value records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(cache_key, payload, _CACHE_TIMEOUT)
            return Response(payload)

        serializer = ContractValueSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "Contract value records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(cache_key, payload, _CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/contract-values/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Contract Value Record by ID",
        responses={
            200: openapi.Response("OK", _CV_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single contract value record by its primary key."""
        try:
            instance = ContractValue.objects.get(pk=kwargs["pk"])
        except ContractValue.DoesNotExist:
            return self._error(
                "Contract value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "Contract value record retrieved successfully",
            ContractValueSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/contract-values/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update Contract Value Record",
        operation_description=(
            "Full or partial update of a contract value record. "
            "revised_value and increase_percentage are recalculated automatically."
        ),
        request_body=_CV_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _CV_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of a contract value record.
        Strips read-only calculated fields from the payload before validation.
        All calculated fields are recomputed after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = ContractValue.objects.get(pk=kwargs["pk"])
        except ContractValue.DoesNotExist:
            return self._error(
                "Contract value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        payload = _normalise_payload(request.data)

        serializer = ContractValueSerializer(
            instance, data=payload, partial=partial
        )

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except DjangoValidationError as exc:
            return self._error("Validation failed", errors=exc.message_dict)
        except Exception as exc:
            logger.error(f"ContractValue update error: {exc}", exc_info=True)
            return self._error(
                "Failed to update contract value record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()

        return self._success(
            "Contract value record updated successfully",
            ContractValueSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/contract-values/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete Contract Value Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a contract value record by its primary key."""
        try:
            instance = ContractValue.objects.get(pk=kwargs["pk"])
        except ContractValue.DoesNotExist:
            return self._error(
                "Contract value record not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        project_name = instance.project_name
        contract_type = instance.contract_type
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"Contract value record for '{project_name}' [{contract_type}] deleted successfully",
            {},
        )

    # =========================================================================
    # CUSTOM FILTER ACTIONS
    # =========================================================================

    # -------------------------------------------------------------------------
    # GET /api/contract-values/project/{projectName}/
    # Returns ALL contract types for a given project (SCL + Contractor)
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Contract Values by Project Name",
        operation_description=(
            "Retrieve all contract type records for a given project.\n\n"
            "Returns both SCL and Contractor records (if they exist) for the project.\n"
            "Useful for dashboard contract comparison tables."
        ),
        responses={
            200: openapi.Response("OK", _CV_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve all contract value records for a project (all types).
        Returns both SCL and Contractor records for the same project.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        qs = _build_queryset(project_name=projectName)

        if not qs.exists():
            return self._error(
                f"No contract value records found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._paginated_success(
            request, qs,
            f"Contract value records for project '{projectName.strip()}' retrieved successfully",
        )

    # -------------------------------------------------------------------------
    # GET /api/contract-values/type/{contractType}/
    # Returns all projects for a given contract type
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All Contract Values by Contract Type",
        operation_description=(
            "Retrieve all records for a specific contract type across all projects.\n\n"
            "Valid values: `SCL`, `CONTRACTOR`\n\n"
            "Useful for type-wise analytics and dashboard filtering."
        ),
        responses={
            200: openapi.Response("OK", _CV_RESPONSE_SCHEMA),
            400: "Invalid contract type",
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"type/(?P<contractType>[^/.]+)",
        url_name="by-contract-type",
    )
    def get_by_contract_type(self, request, contractType: str = None):
        """
        Retrieve all contract value records for a specific contract type.
        Supports all projects filtered by SCL or Contractor.
        """
        if not contractType or not contractType.strip():
            return self._error("contractType is required.")

        # Validate the contract type against the enum
        contract_type = _normalize_contract_type(contractType.strip())
        valid_types = [c.value for c in ContractValue.ContractType]
        if contract_type not in valid_types:
            return self._error(
                f"Invalid contractType '{contractType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        qs = _build_queryset(contract_type=contract_type)

        if not qs.exists():
            return self._error(
                f"No contract value records found for contractType '{contractType}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._paginated_success(
            request, qs,
            f"Contract value records for type '{contractType.strip()}' retrieved successfully",
        )

    # -------------------------------------------------------------------------
    # GET /api/contract-values/project/{projectName}/type/{contractType}/
    # Exact lookup: one specific record
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get Contract Value by Project Name and Contract Type",
        operation_description=(
            "Retrieve the exact contract value record for a specific project + type combination.\n\n"
            "**Examples:**\n"
            "- `GET /api/contract-values/project/PMC Smart City/type/SCL/`\n"
            "- `GET /api/contract-values/project/PMC Smart City/type/Contractor/`\n\n"
            "Ideal for dashboard KPI cards that display SCL and Contractor values side-by-side."
        ),
        responses={
            200: openapi.Response("OK", _CV_RESPONSE_SCHEMA),
            400: "Invalid contract type",
            404: "Not found",
        },
        tags=["Contract Values"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)/type/(?P<contractType>[^/.]+)",
        url_name="by-project-and-type",
    )
    def get_by_project_and_type(
        self, request, projectName: str = None, contractType: str = None
    ):
        """
        Retrieve the exact contract value record for a (projectName, contractType) pair.
        Case-insensitive project name lookup.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")
        if not contractType or not contractType.strip():
            return self._error("contractType is required.")

        # Validate the contract type
        contract_type = _normalize_contract_type(contractType.strip())
        valid_types = [c.value for c in ContractValue.ContractType]
        if contract_type not in valid_types:
            return self._error(
                f"Invalid contractType '{contractType}'. "
                f"Must be one of: {', '.join(valid_types)}."
            )

        try:
            instance = ContractValue.objects.get(
                project_name__iexact=projectName.strip(),
                contract_type=contract_type,
            )
        except ContractValue.DoesNotExist:
            return self._error(
                f"No contract value record found for project '{projectName}' "
                f"with contractType '{contractType}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            f"Contract value record for '{projectName.strip()}' [{contractType.strip()}] "
            "retrieved successfully",
            ContractValueSerializer(instance).data,
        )
