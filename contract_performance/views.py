from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import ContractPerformance
from .serializers import ContractPerformanceSerializer


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


class ContractPerformanceViewSet(viewsets.ModelViewSet):
    """
    Contract Performance endpoints.
    
    Endpoints:
    - POST   /api/contract-performance/                 -> Billing Site Engineer creates
    - GET    /api/contract-performance/                 -> Billing Site Engineer views all
    - GET    /api/contract-performance/{id}/            -> Billing Site Engineer retrieves single
    - PUT    /api/contract-performance/{id}/            -> Billing Site Engineer updates (full)
    - PATCH  /api/contract-performance/{id}/            -> Billing Site Engineer updates (partial)
    - DELETE /api/contract-performance/{id}/            -> Billing Site Engineer deletes
    """
    
    queryset = ContractPerformance.objects.all()
    serializer_class = ContractPerformanceSerializer
    # Using role from request (temporary). Do not require auth for now.
    permission_classes = [AllowAny]
    
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
        Filtering:
        - project_name: partial match (case-insensitive)
        - date: filter by created_at date (YYYY-MM-DD)
        - performance_status: filter by status (red, yellow, green)
        """
        qs = ContractPerformance.objects.all()
        
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name)
        
        date_str = self.request.query_params.get("date")
        if date_str:
            d = parse_date(date_str)
            if d:
                qs = qs.filter(created_at__date=d)
        
        performance_status = self.request.query_params.get("performance_status")
        if performance_status:
            qs = qs.filter(performance_status=performance_status)
        
        return qs.order_by("-created_at")
    
    def _check_billing_engineer_permission(self, request, action_name="perform this action"):
        """
        Check if user has Billing Site Engineer role.
        Returns (is_allowed, error_response) tuple.
        """
        role = _get_role_from_request(request)
        if role != "Billing Site Engineer":
            return False, Response(
                {"detail": f"Only Billing Site Engineer can {action_name} (role='Billing Site Engineer')."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return True, None
    
    @swagger_auto_schema(
        operation_description="List all Contract Performance records. Filter by project_name, date, and performance_status.",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (case-insensitive partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Filter by created date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('performance_status', openapi.IN_QUERY, description="Filter by performance status (red, yellow, green)", type=openapi.TYPE_STRING),
            openapi.Parameter('role', openapi.IN_QUERY, description="User role (required: 'Billing Site Engineer')", type=openapi.TYPE_STRING),
        ],
        responses={200: ContractPerformanceSerializer(many=True), 403: "Forbidden"}
    )
    def list(self, request, *args, **kwargs):
        """List all contract performance records (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "view contract performance")
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
        headers = self.get_success_headers(serializer.data)
        return Response(
            self.get_serializer(performance).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @swagger_auto_schema(
        operation_description="Retrieve a single Contract Performance record by ID.",
        responses={200: ContractPerformanceSerializer, 403: "Forbidden", 404: "Not Found"}
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve single contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "view contract performance")
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
        return self.update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Delete a Contract Performance record.",
        responses={204: "No Content", 403: "Forbidden", 404: "Not Found"}
    )
    def destroy(self, request, *args, **kwargs):
        """Delete contract performance record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "delete contract performance")
        if not is_allowed:
            return error_response
        
        return super().destroy(request, *args, **kwargs)
