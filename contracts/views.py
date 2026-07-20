from decimal import Decimal, InvalidOperation, DivisionByZero

from django.core.cache import cache
from django.utils.dateparse import parse_date
from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Contract
from .serializers import ContractSerializer
from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from accounts.rbac_checks import enforce_project_write_by_name
from core.cache_keys import build_rbac_list_cache_key, invalidate_list_cache


# Role normalization mapping for case-insensitive input
ROLE_NORMALIZATION_MAP = {
    "billing site engineer": "Billing Site Engineer",
    "team leader": "Team Leader",
    "pmc head": "PMC Head",
    "ceo": "CEO",
    "coordinator": "Coordinator",
}


def _normalize_role_input(role_input: str) -> str | None:
    """
    Normalize role input to canonical role values.
    - Strip whitespace
    - Convert to lowercase for matching
    - Map to correct canonical role name
    """
    if not role_input:
        return None

    # Strip whitespace and convert to lowercase for matching
    normalized_input = role_input.strip().lower()

    # Map to canonical role name
    return ROLE_NORMALIZATION_MAP.get(normalized_input)


def _get_role_from_request(request) -> str | None:
    """
    Role extraction with case-insensitive normalization.
    Supports multiple input methods for flexibility.

    Priority order:
    1. request.data['role'] (for POST/PUT bodies)
    2. query param: ?role=ceo (for GET requests)
    3. header: X-Role: ceo (fallback)

    All inputs are normalized to canonical role names.
    """
    role = None
    try:
        role = request.data.get("role")
    except Exception:
        role = None
    if not role:
        role = request.query_params.get("role") or request.headers.get("X-Role")

    # Normalize role input to canonical values
    return _normalize_role_input(role)


class ContractViewSet(viewsets.ModelViewSet):
    """
    Contract workflow endpoints.

    Endpoints:
    - POST   /api/contracts/                 -> Billing Site Engineer creates (status=pending)
    - GET    /api/contracts/                 -> Dashboard: ONLY approved contracts
    - GET    /api/contracts/all/             -> Admin view: all contracts (CEO only for now)
    - POST   /api/contracts/{id}/approve/    -> CEO approves and triggers calculations
    - POST   /api/contracts/{id}/reject/     -> CEO rejects
    - GET    /api/contracts/summary/         -> Dashboard totals (ONLY approved)
    """

    queryset = Contract.objects.all()
    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.BILLING

    def initial(self, request, *args, **kwargs):
        """
        Initialize the viewset and cache the role for this request.
        """
        super().initial(request, *args, **kwargs)
        # Cache role once per request to avoid multiple extractions
        self._cached_role = _get_role_from_request(request)

    def _get_role_from_cache(self) -> str | None:
        """Get the cached role for this request."""
        return getattr(self, '_cached_role', None)

    def _get_cache_key(self, request, action="list"):
        """Generate RBAC-aware cache key based on action and query parameters."""
        params = []
        project_name = request.query_params.get("project_name", "").strip()
        if project_name:
            params.append(f"project:{project_name}")

        date_str = request.query_params.get("date", "").strip()
        if date_str:
            params.append(f"date:{date_str}")

        # Include role in cache key since it affects filtering
        role = self._get_role_from_cache()
        if role:
            params.append(f"role:{role}")

        return build_rbac_list_cache_key(
            f"contracts_{action}",
            request,
            extra_parts=params,
            use_query_string=False,
        )

    def _get_latest_pending_contract(self, project_name: str) -> Contract | None:
        """
        Helper method to get the latest pending contract for a project.
        Reusable across approve and reject methods.
        """
        return Contract.objects.filter(
            project_name__iexact=project_name.strip(),
            status=Contract.Status.PENDING
        ).order_by("-created_at").first()

    def _invalidate_contract_cache(self):
        """
        Safely invalidate contract-related cache.
        Works with LocMemCache (development) and Redis (production).
        """
        invalidate_list_cache("contracts_list")
        invalidate_list_cache("contracts_summary")

    # ---- Swagger schemas (fix DecimalField showing as string in Swagger UI) ----
    # drf-yasg (Swagger 2.0) often models Decimal as "string". Swagger UI then
    # refuses numeric input. We override request bodies to accept "number".
    _contract_create_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name", "original_contract_value", "created_by"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "original_contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=1000000.0),
            "approved_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=50000.0),
            "pending_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=25000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )

    _contract_update_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "original_contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=1000000.0),
            "approved_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=50000.0),
            "pending_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=25000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )

    _ceo_action_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="CEO"),
        },
    )

    _ceo_project_action_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="CEO"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
        },
    )

    def get_queryset(self):
        """
        Optimized queryset with action-specific logic and field selection.
        """
        # Use .only() to fetch only required fields for performance
        # Include all fields that serializer needs for both list and detail views
        qs = Contract.objects.only(
            'id', 'project_name', 'original_contract_value', 'approved_vo',
            'pending_vo', 'revised_contract_value', 'approved_vo_percentage',
            'status', 'created_by', 'approved_by', 'created_at', 'updated_at'
        )

        # Apply different logic based on action
        if self.action == "list":
            # For list view: apply filtering and status restrictions
            project_name = self.request.query_params.get("project_name")
            if project_name:
                # Normalize project_name for consistent filtering
                normalized_project_name = project_name.strip()
                qs = qs.filter(project_name__icontains=normalized_project_name)

            date_str = self.request.query_params.get("date")
            if date_str:
                d = parse_date(date_str.strip())
                if d:
                    qs = qs.filter(created_at__date=d)

            # Default list endpoint returns approved only for regular users
            # PMC Head and CEO can see all contracts
            role = self._get_role_from_cache()
            if role not in ["PMC Head", "CEO"]:
                qs = qs.filter(status=Contract.Status.APPROVED)

            qs = self._apply_project_rbac_filter(qs)
            return qs.order_by("-created_at")
        else:
            return self._apply_project_rbac_filter(qs)

    def _apply_project_rbac_filter(self, qs):
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            return filter_queryset_by_project_access(qs, user, "project_name")
        return qs

    @swagger_auto_schema(
        operation_description="Retrieve a single contract by ID. Dashboard users see only approved contracts.",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: billing site engineer | team leader | pmc head | ceo | coordinator (case-insensitive)",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ContractSerializer, 403: "Forbidden", 404: "Not Found"}
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve single contract.
        For dashboard: only return approved contracts.
        For CEO/admin: can retrieve any contract via /api/contracts/all/{id}/ or by checking role.
        """
        instance = self.get_object()

        # If not CEO and contract is not approved, return 404 (hide unapproved contracts)
        role = self._get_role_from_cache()
        if role != "CEO" and instance.status != Contract.Status.APPROVED:
            return Response(
                {"detail": "Contract not found or not approved."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Dashboard: List approved contracts. Filter by project_name and date. PMC Head/CEO see all contracts.",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (case-insensitive partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Filter by created date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: billing site engineer | team leader | pmc head | ceo | coordinator (case-insensitive)",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ContractSerializer(many=True), 403: "Forbidden"}
    )
    def list(self, request, *args, **kwargs):
        """
        Dashboard list: ONLY approved contracts.
        Returns clean structured response format with caching.
        """
        cache_key = self._get_cache_key(request, "list")
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)

        def clean(item):
            return {
                "project_name": item["project_name"],
                "original_contract_value": item["original_contract_value"],
                "approved_vo": item["approved_vo"],
                "approved_vo_percentage": item["approved_vo_percentage"],
                "revised_contract_value": item["revised_contract_value"],
                "pending_vo": item["pending_vo"],
                "status": item["status"],
            }

        data = [clean(x) for x in serializer.data]
        if page is not None:
            response = self.get_paginated_response(data)
            cache.set(cache_key, response.data, 300)
            return response
        cache.set(cache_key, data, 300)
        return Response(data)

    @swagger_auto_schema(
        operation_description="Create contract (Billing Site Engineer). Status is forced to pending.",
        request_body=_contract_create_schema,
        responses={201: ContractSerializer, 400: "Validation Error", 403: "Forbidden"},
    )
    def create(self, request, *args, **kwargs):
        """
        Billing Site Engineer creates contract.
        Business rule: status is forced to pending.

        Permission (simple): request.data['role'] must be 'Billing Site Engineer'
        """
        role = _get_role_from_request(request)
        if role not in ["Billing Site Engineer", "Team Leader"]:
            return Response(
                {"detail": "Only Billing Site Engineer or Team Leader can create contracts (role='Billing Site Engineer' or 'Team Leader')."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enforce_project_write_by_name(
            request.user,
            serializer.validated_data.get("project_name"),
            RBACDomain.BILLING,
        )
        # Explicitly set status to PENDING (prevent any auto-approval)
        contract = serializer.save(status=Contract.Status.PENDING)

        # Cache invalidation: clear relevant cache keys after creation
        self._invalidate_contract_cache()

        headers = self.get_success_headers(serializer.data)
        return Response(self.get_serializer(contract).data, status=status.HTTP_201_CREATED, headers=headers)

    @swagger_auto_schema(
        operation_description="Update contract (Billing Site Engineer). Approved contracts cannot be edited.",
        request_body=_contract_update_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden"},
    )
    def update(self, request, *args, **kwargs):
        """
        Billing Site Engineer can update while not approved.
        (Simple version) role check using request.data['role'].
        """
        role = _get_role_from_request(request)
        if role not in ["Billing Site Engineer", "Team Leader"]:
            return Response(
                {"detail": "Only Billing Site Engineer or Team Leader can update contracts."},
                status=status.HTTP_403_FORBIDDEN,
            )

        instance = self.get_object()
        if instance.status == Contract.Status.APPROVED:
            return Response(
                {"detail": "Approved contracts cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = super().update(request, *args, **kwargs)

        # Cache invalidation: clear relevant cache keys after update
        self._invalidate_contract_cache()

        return result

    @swagger_auto_schema(
        operation_description="Admin view: List ALL contracts (approved, pending, rejected). PMC Head, Coordinator, Billing Site Engineer access.",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: billing site engineer | team leader | pmc head | ceo | coordinator (case-insensitive)",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ContractSerializer(many=True), 403: "Forbidden"}
    )
    @action(detail=False, methods=["get"], url_path="all")
    def all_contracts(self, request):
        """
        Admin view: return all contracts (approved, pending, rejected).
        Permission: PMC Head, Coordinator, Billing Site Engineer.
        """
        role = self._get_role_from_cache()
        allowed_roles = ["Billing Site Engineer", "Team Leader", "PMC Head", "CEO", "Coordinator"]
        if role not in allowed_roles:
            return Response(
                {"detail": f"Access denied. Allowed roles: {', '.join(allowed_roles)}."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Return ALL contracts (no status filtering) with optimized query
        qs = Contract.objects.only(
            'id', 'project_name', 'original_contract_value', 'approved_vo',
            'pending_vo', 'revised_contract_value', 'approved_vo_percentage',
            'status', 'created_by', 'approved_by', 'created_at', 'updated_at'
        ).order_by("-created_at")

        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="approve")
    @swagger_auto_schema(
        operation_description=(
            "CEO approves the latest PENDING contract for the given project_name."
        ),
        request_body=_ceo_project_action_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"},
    )
    def approve(self, request):
        """
        Approve by project_name (instead of id).
        Picks the latest PENDING contract for that project.
        """
        role = _get_role_from_request(request)
        if role != "CEO":
            return Response({"detail": "Only CEO can approve contracts."}, status=status.HTTP_403_FORBIDDEN)

        project_name = request.data.get("project_name") if hasattr(request, "data") else None
        if not project_name:
            return Response({"detail": "project_name is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Use helper method to get latest pending contract
        contract = self._get_latest_pending_contract(project_name)
        if not contract:
            return Response(
                {"detail": "No pending contract found for this project_name."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Optimized calculation: keep all values in Decimal, no float conversions
        try:
            original = contract.original_contract_value
            approved_vo = contract.approved_vo
            revised = original + approved_vo
            # Keep percentage in Decimal for precision
            approved_pct = (approved_vo / original) * Decimal("100")
        except (InvalidOperation, DivisionByZero):
            return Response(
                {"detail": "Cannot calculate values. Ensure original_contract_value > 0 and numbers are valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        contract.revised_contract_value = revised
        contract.approved_vo_percentage = approved_pct
        contract.status = Contract.Status.APPROVED
        contract.approved_by = "CEO"
        contract.save(
            update_fields=[
                "revised_contract_value",
                "approved_vo_percentage",
                "status",
                "approved_by",
                "updated_at",
            ]
        )

        # Cache invalidation: clear relevant cache keys after approval
        self._invalidate_contract_cache()

        return Response(self.get_serializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="reject")
    @swagger_auto_schema(
        operation_description="CEO rejects the latest PENDING contract for the given project_name.",
        request_body=_ceo_project_action_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"},
    )
    def reject(self, request):
        """
        Reject by project_name (instead of id).
        Picks the latest PENDING contract for that project.
        """
        role = _get_role_from_request(request)
        if role != "CEO":
            return Response({"detail": "Only CEO can reject contracts."}, status=status.HTTP_403_FORBIDDEN)

        project_name = request.data.get("project_name") if hasattr(request, "data") else None
        if not project_name:
            return Response({"detail": "project_name is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Use helper method to get latest pending contract
        contract = self._get_latest_pending_contract(project_name)
        if not contract:
            return Response(
                {"detail": "No pending contract found for this project_name."},
                status=status.HTTP_404_NOT_FOUND,
            )

        contract.status = Contract.Status.REJECTED
        contract.approved_by = "CEO"
        contract.save(update_fields=["status", "approved_by", "updated_at"])

        # Cache invalidation: clear relevant cache keys after rejection
        self._invalidate_contract_cache()

        return Response(self.get_serializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """
        Dashboard summary totals for ONLY approved contracts:
        - Original Contract Value
        - Approved VO(s)
        - Revised/Remeasured Contract Value
        - Potential/Pending VO(s)

        Results are cached for 5 minutes.
        """
        # Check cache first
        cache_key = self._get_cache_key(request, "summary")
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        # Calculate summary with optimized query
        qs = Contract.objects.filter(status=Contract.Status.APPROVED).only(
            'original_contract_value', 'approved_vo', 'revised_contract_value', 'pending_vo'
        )
        totals = qs.aggregate(
            original_contract_value=Sum("original_contract_value"),
            approved_vo=Sum("approved_vo"),
            revised_contract_value=Sum("revised_contract_value"),
            pending_vo=Sum("pending_vo"),
        )

        # Normalize None -> 0 using Decimal for consistency
        def n(v):
            return v if v is not None else Decimal("0")

        response_data = {
            "original_contract_value_total": n(totals["original_contract_value"]),
            "approved_vo_total": n(totals["approved_vo"]),
            "revised_contract_value_total": n(totals["revised_contract_value"]),
            "pending_vo_total": n(totals["pending_vo"]),
        }

        # Cache the response for 5 minutes
        cache.set(cache_key, response_data, 300)

        return Response(response_data, status=status.HTTP_200_OK)

# Create your views here.
