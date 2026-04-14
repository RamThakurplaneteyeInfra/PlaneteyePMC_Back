from django.core.cache import cache
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import InvoicingInformation
from .serializers import InvoicingInformationSerializer


def _get_role_from_request(request) -> str | None:
    """
    Simple role extraction (temporary).
    Requirement says: use request.data['role'] for now.

    We also support:
    - query param: ?role=Billing Site Engineer (helps for GET)
    - header: X-Role: Billing Site Engineer
    """
    role = None
    try:
        role = request.data.get("role")
    except Exception:
        role = None
    if not role:
        role = request.query_params.get("role") or request.headers.get("X-Role")
    return role


class InvoicingInformationViewSet(viewsets.ModelViewSet):
    """
    Invoicing Information endpoints.
    
    Endpoints:
    - POST   /api/invoicing/                 -> Billing Site Engineer creates
    - GET    /api/invoicing/                 -> Billing Site Engineer, PMC Head, CEO, or Coordinator views all
    - GET    /api/invoicing/{id}/            -> Billing Site Engineer, PMC Head, CEO, or Coordinator retrieves single
    - PUT    /api/invoicing/{id}/            -> Billing Site Engineer updates (full)
    - PATCH  /api/invoicing/{id}/            -> Billing Site Engineer updates (partial)
    - DELETE /api/invoicing/{id}/            -> Billing Site Engineer deletes
    """
    
    queryset = InvoicingInformation.objects.all()
    serializer_class = InvoicingInformationSerializer
    # Using role from request (temporary). Do not require auth for now.
    permission_classes = [AllowAny]
    pagination_class = PageNumberPagination

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # Extract and normalize role once
        self.request_role = _get_role_from_request(request)
        if self.request_role:
            self.request_role = self.request_role.strip().lower()
    
    # ---- Swagger schemas (fix DecimalField showing as string in Swagger UI) ----
    _invoicing_create_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name", "gross_billed", "net_billed_without_vat", "net_collected", "created_by"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "gross_billed": openapi.Schema(type=openapi.TYPE_NUMBER, example=120000000.0),
            "net_billed_without_vat": openapi.Schema(type=openapi.TYPE_NUMBER, example=100000000.0),
            "net_collected": openapi.Schema(type=openapi.TYPE_NUMBER, example=80000000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    _invoicing_update_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "gross_billed": openapi.Schema(type=openapi.TYPE_NUMBER, example=120000000.0),
            "net_billed_without_vat": openapi.Schema(type=openapi.TYPE_NUMBER, example=100000000.0),
            "net_collected": openapi.Schema(type=openapi.TYPE_NUMBER, example=80000000.0),
            "updated_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    def get_queryset(self):
        """
        Filtering:
        - project_name: partial match (case-insensitive)
        - date: filter by created_at date (YYYY-MM-DD)
        """
        qs = InvoicingInformation.objects.only(
            "id", "project_name", "gross_billed", "net_billed_without_vat",
            "net_collected", "net_due", "created_by", "updated_by",
            "created_at", "updated_at"
        )

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name.strip())

        date_str = self.request.query_params.get("date")
        if date_str:
            d = parse_date(date_str)
            if d:
                qs = qs.filter(created_at__date=d)

        return qs.order_by("-created_at")
    
    def _check_billing_engineer_permission(self, action_name="perform this action"):
        """
        Check if user has Billing Site Engineer role.
        Returns (is_allowed, error_response) tuple.
        """
        if self.request_role != "billing site engineer":
            return False, Response(
                {"detail": f"Only Billing Site Engineer can {action_name} (role='Billing Site Engineer')."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return True, None

    def _check_view_invoicing_permission(self):
        """List/retrieve: Billing Site Engineer, PMC Head, CEO, or Coordinator (read-only for the latter)."""
        if self.request_role in ("billing site engineer", "pmc head", "ceo", "coordinator"):
            return True, None
        return False, Response(
            {
                "detail": "Only Billing Site Engineer, PMC Head, CEO, or Coordinator can view invoicing information "
                "(pass role as query param or X-Role header)."
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    @swagger_auto_schema(
        operation_description="List all Invoicing Information records. Filter by project_name and date.",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (case-insensitive partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Filter by created date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: Billing Site Engineer | PMC Head | CEO | Coordinator",
                type=openapi.TYPE_STRING,
                required=False
            ),
            openapi.Parameter(
                'X-Role',
                openapi.IN_HEADER,
                description="User role header: Billing Site Engineer | PMC Head | CEO | Coordinator",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: InvoicingInformationSerializer(many=True), 403: "Forbidden"}
    )
    def list(self, request, *args, **kwargs):
        """List invoicing records (Billing Site Engineer, PMC Head, CEO, or Coordinator)."""
        cache_key = f"invoicing_list:{request.get_full_path()}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        is_allowed, error_response = self._check_view_invoicing_permission()
        if not is_allowed:
            return error_response

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, 300)  # 5 minutes
        return response
    
    @swagger_auto_schema(
        operation_description="Create a new Invoicing Information record.",
        request_body=_invoicing_create_schema,
        responses={201: InvoicingInformationSerializer, 400: "Bad Request - Validation errors", 403: "Forbidden"}
    )
    def perform_create(self, serializer):
        super().perform_create(serializer)
        # Cache invalidation
        cache.delete_pattern("invoicing_list:*")
        cache.delete_pattern("invoicing_retrieve:*")

    def create(self, request, *args, **kwargs):
        """Create invoicing record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission("create invoicing information")
        if not is_allowed:
            return error_response

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @swagger_auto_schema(
        operation_description="Retrieve a single Invoicing Information record by ID.",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: Billing Site Engineer | PMC Head | CEO | Coordinator",
                type=openapi.TYPE_STRING,
                required=False
            ),
            openapi.Parameter(
                'X-Role',
                openapi.IN_HEADER,
                description="User role header: Billing Site Engineer | PMC Head | CEO | Coordinator",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: InvoicingInformationSerializer, 403: "Forbidden", 404: "Not Found"}
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve single invoicing record (Billing Site Engineer, PMC Head, CEO, or Coordinator)."""
        cache_key = f"invoicing_retrieve:{kwargs['pk']}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        is_allowed, error_response = self._check_view_invoicing_permission()
        if not is_allowed:
            return error_response

        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, 300)  # 5 minutes
        return response
    
    @swagger_auto_schema(
        operation_description="Update an Invoicing Information record (full update). Use PATCH for partial update.",
        request_body=_invoicing_update_schema,
        responses={200: InvoicingInformationSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def perform_update(self, serializer):
        super().perform_update(serializer)
        # Cache invalidation
        cache.delete_pattern("invoicing_list:*")
        cache.delete_pattern("invoicing_retrieve:*")

    def update(self, request, *args, **kwargs):
        """Update invoicing record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission("update invoicing information")
        if not is_allowed:
            return error_response

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_description="Partially update an Invoicing Information record.",
        request_body=_invoicing_update_schema,
        responses={200: InvoicingInformationSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update invoicing record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission("update invoicing information")
        if not is_allowed:
            return error_response

        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Delete an Invoicing Information record.",
        responses={204: "No Content", 403: "Forbidden", 404: "Not Found"}
    )
    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        # Cache invalidation
        cache.delete_pattern("invoicing_list:*")
        cache.delete_pattern("invoicing_retrieve:*")

    def destroy(self, request, *args, **kwargs):
        """Delete invoicing record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission("delete invoicing information")
        if not is_allowed:
            return error_response

        return super().destroy(request, *args, **kwargs)
