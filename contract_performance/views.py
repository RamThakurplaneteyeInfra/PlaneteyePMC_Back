from django.core.cache import cache
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
"""
    The above code defines a Django REST framework viewset for managing Contract Performance records
    with various endpoints and permission checks based on user roles.

    :param request: The `request` parameter in the context of Django REST framework represents the HTTP
    request that is received by the view. It contains information about the request, such as headers,
    query parameters, data, user authentication, and more. The request object provides access to details
    of the incoming request, allowing you to
    :return: The code provided defines a Django REST framework viewset for managing Contract Performance
    records. It includes methods for creating, retrieving, updating, partially updating, and deleting
    contract performance records. The viewset also includes permission checks based on the role of the
    user making the request.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import ContractPerformance
from .serializers import ContractPerformanceSerializer


class ContractPerformancePagination(PageNumberPagination):
    """Pagination for contract performance records."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


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
    Simple role extraction with case-insensitive normalization (temporary).
    Requirement says: use request.data['role'] for now.

    We support:
    - query param: ?role=billing site engineer (helps for GET) - case-insensitive
    - header: X-Role: billing site engineer - case-insensitive (backend support only)

    Role input is normalized to canonical values before validation.
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


class ContractPerformanceViewSet(viewsets.ModelViewSet):
    """
    Contract Performance endpoints.

    Endpoints:
    - POST   /api/contract-performance/                 -> Billing Site Engineer creates
    - GET    /api/contract-performance/                 -> Billing Site Engineer, PMC Head, CEO, or Coordinator views all
    - GET    /api/contract-performance/{id}/            -> Billing Site Engineer, PMC Head, CEO, or Coordinator retrieves single
    - PUT    /api/contract-performance/{id}/            -> Billing Site Engineer updates (full)
    - PATCH  /api/contract-performance/{id}/            -> Billing Site Engineer updates (partial)
    - DELETE /api/contract-performance/{id}/            -> Billing Site Engineer deletes
    """

    queryset = ContractPerformance.objects.all()
    serializer_class = ContractPerformanceSerializer
    permission_classes = [AllowAny]
    pagination_class = ContractPerformancePagination

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

    def _get_cache_key(self, request):
        """Generate cache key based on query parameters."""
        params = []
        project_name = request.query_params.get("project_name", "").strip()
        if project_name:
            params.append(f"project:{project_name}")

        date_str = request.query_params.get("date", "").strip()
        if date_str:
            params.append(f"date:{date_str}")

        status = request.query_params.get("performance_status", "").strip()
        if status:
            params.append(f"status:{status}")

        param_str = "|".join(params) if params else "all"
        return f"contract_performance_list:{param_str}"
    
    # ---- Swagger schemas (fix DecimalField showing as string in Swagger UI) ----
    _performance_create_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name", "contract_value", "earned_value", "actual_billed", "created_by"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=140000000.0),
            "earned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=134288000.0),
            "actual_billed": openapi.Schema(type=openapi.TYPE_NUMBER, example=120000000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    _performance_update_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=140000000.0),
            "earned_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=134288000.0),
            "actual_billed": openapi.Schema(type=openapi.TYPE_NUMBER, example=120000000.0),
            "updated_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    def get_queryset(self):
        """
        Optimized queryset with action-specific logic and field selection.
        """
        # Use .only() to fetch only required fields for performance
        qs = ContractPerformance.objects.only(
            'id', 'project_name', 'contract_value', 'earned_value',
            'earned_value_percentage', 'actual_billed', 'actual_billed_percentage',
            'variance', 'variance_percentage', 'performance_status',
            'created_by', 'updated_by', 'created_at', 'updated_at'
        )

        # Apply different logic based on action
        if self.action == 'list':
            # For list view: apply filtering with normalized inputs
            project_name = self.request.query_params.get("project_name")
            if project_name:
                # Normalize input by stripping whitespace
                qs = qs.filter(project_name__icontains=project_name.strip())

            date_str = self.request.query_params.get("date")
            if date_str:
                d = parse_date(date_str.strip())
                if d:
                    qs = qs.filter(created_at__date=d)

            performance_status = self.request.query_params.get("performance_status")
            if performance_status:
                qs = qs.filter(performance_status=performance_status.strip())

            return qs.order_by("-created_at")
        else:
            # For retrieve/detail view: return full queryset without filtering
            return qs
    
    def _check_billing_engineer_permission(self, request, action_name="perform this action"):
        """
        Check if user has Billing Site Engineer role using cached role.
        Returns (is_allowed, error_response) tuple.
        """
        role = self._get_role_from_cache()
        if role not in ["Billing Site Engineer", "Team Leader"]:
            return False, Response(
                {"detail": f"Only Billing Site Engineer or Team Leader can {action_name} (role='Billing Site Engineer' or 'Team Leader')."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return True, None

    def _check_view_contract_performance_permission(self, request):
        """List/retrieve: Billing Site Engineer, PMC Head, CEO, or Coordinator using cached role."""
        role = self._get_role_from_cache()
        if role in ("Billing Site Engineer", "Team Leader", "PMC Head", "CEO", "Coordinator"):
            return True, None
        return False, Response(
            {
                "detail": "Only Billing Site Engineer, Team Leader, PMC Head, CEO, or Coordinator can view contract performance "
                "(pass role as query param or X-Role header)."
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    def _invalidate_contract_performance_cache(self):
        """
        Safely invalidate contract performance cache.
        Works with LocMemCache (development) and Redis (production).
        """
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern("contract_performance_list:*")
            else:
                cache.clear()
        except Exception:
            try:
                cache.clear()
            except Exception:
                pass

    @swagger_auto_schema(
        operation_description="List all Contract Performance records. Filter by project_name, date, and performance_status.",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (case-insensitive partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Filter by created date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('performance_status', openapi.IN_QUERY, description="Filter by performance status (red, yellow, green)", type=openapi.TYPE_STRING),
            openapi.Parameter('page', openapi.IN_QUERY, description='Page number for pagination', type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('page_size', openapi.IN_QUERY, description='Number of records per page (max 100)', type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: billing site engineer | team leader | pmc head | ceo | coordinator (case-insensitive)",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ContractPerformanceSerializer(many=True), 403: "Forbidden"}
    )
    @method_decorator(cache_page(300))  # 5 minutes cache
    def list(self, request, *args, **kwargs):
        """List contract performance with caching (Billing Site Engineer, PMC Head, CEO, or Coordinator)."""
        is_allowed, error_response = self._check_view_contract_performance_permission(request)
        if not is_allowed:
            return error_response

        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Create a new Contract Performance record. All calculated fields (percentages, variance, performance_status) are auto-calculated.",
        request_body=_performance_create_schema,
        responses={201: ContractPerformanceSerializer, 400: "Bad Request - Validation errors", 403: "Forbidden"}
    )
    def create(self, request, *args, **kwargs):
        """Create contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "create contract performance")
        if not is_allowed:
            return error_response

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        performance = serializer.save()

        # Cache invalidation (safe for LocMemCache)
        self._invalidate_contract_performance_cache()

        headers = self.get_success_headers(serializer.data)
        return Response(
            self.get_serializer(performance).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @swagger_auto_schema(
        operation_description="Retrieve a single Contract Performance record by ID.",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: billing site engineer | team leader | pmc head | ceo | coordinator (case-insensitive)",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ContractPerformanceSerializer, 403: "Forbidden", 404: "Not Found"}
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve single contract performance record (Billing Site Engineer, PMC Head, CEO, or Coordinator)."""
        is_allowed, error_response = self._check_view_contract_performance_permission(request)
        if not is_allowed:
            return error_response

        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Update a Contract Performance record (full update). Use PATCH for partial update. All calculated fields are auto-updated.",
        request_body=_performance_update_schema,
        responses={200: ContractPerformanceSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def update(self, request, *args, **kwargs):
        """Update contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "update contract performance")
        if not is_allowed:
            return error_response

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Cache invalidation (safe for LocMemCache)
        self._invalidate_contract_performance_cache()

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Partially update a Contract Performance record. All calculated fields are auto-updated.",
        request_body=_performance_update_schema,
        responses={200: ContractPerformanceSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "update contract performance")
        if not is_allowed:
            return error_response

        kwargs['partial'] = True
        result = self.update(request, *args, **kwargs)
        return result

    @swagger_auto_schema(
        operation_description="Delete a Contract Performance record.",
        responses={204: "No Content", 403: "Forbidden", 404: "Not Found"}
    )
    def destroy(self, request, *args, **kwargs):
        """Delete contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "delete contract performance")
        if not is_allowed:
            return error_response

        result = super().destroy(request, *args, **kwargs)

        # Cache invalidation (safe for LocMemCache)
        self._invalidate_contract_performance_cache()

        return result
