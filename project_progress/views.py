from datetime import date, timedelta
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import ProjectProgressStatus
from .serializers import ProjectProgressStatusSerializer


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


class ProjectProgressStatusViewSet(viewsets.ModelViewSet):
    """
    Project Progress Status endpoints.
    
    Endpoints:
    - POST   /api/project-progress/                 -> Billing Site Engineer creates
    - GET    /api/project-progress/                 -> Billing Site Engineer views all
    - GET    /api/project-progress/{id}/            -> Billing Site Engineer retrieves single
    - PUT    /api/project-progress/{id}/            -> Billing Site Engineer updates (full)
    - PATCH  /api/project-progress/{id}/            -> Billing Site Engineer updates (partial)
    - DELETE /api/project-progress/{id}/            -> Billing Site Engineer deletes
    """
    
    queryset = ProjectProgressStatus.objects.all()
    serializer_class = ProjectProgressStatusSerializer
    # Disable authentication completely
    authentication_classes = []
    permission_classes = [AllowAny]
    
    # ---- Swagger schemas (fix FloatField showing as string in Swagger UI) ----
    _progress_create_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name", "progress_month", "monthly_plan", "cumulative_plan", "monthly_actual", "cumulative_actual", "created_by"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "progress_month": openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE, example="2024-01-01", description="First day of the month (YYYY-MM-01)"),
            "monthly_plan": openapi.Schema(type=openapi.TYPE_NUMBER, example=2.56, description="Planned progress for this month (0-100)"),
            "cumulative_plan": openapi.Schema(type=openapi.TYPE_NUMBER, example=2.56, description="Cumulative planned progress (0-100)"),
            "monthly_actual": openapi.Schema(type=openapi.TYPE_NUMBER, example=1.31, description="Actual progress for this month (0-100)"),
            "cumulative_actual": openapi.Schema(type=openapi.TYPE_NUMBER, example=1.31, description="Cumulative actual progress (0-100)"),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    _progress_update_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "progress_month": openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE, example="2024-01-01"),
            "monthly_plan": openapi.Schema(type=openapi.TYPE_NUMBER, example=2.56),
            "cumulative_plan": openapi.Schema(type=openapi.TYPE_NUMBER, example=2.56),
            "monthly_actual": openapi.Schema(type=openapi.TYPE_NUMBER, example=1.31),
            "cumulative_actual": openapi.Schema(type=openapi.TYPE_NUMBER, example=1.31),
            "updated_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )
    
    def get_queryset(self):
        """
        Filtering:
        - project_name: partial match (case-insensitive)
        - start_month: filter from this month onwards (YYYY-MM-DD, first day of month)
        - end_month: filter up to this month (YYYY-MM-DD, first day of month)
        - month: filter by specific month (YYYY-MM-DD, first day of month)
        """
        qs = ProjectProgressStatus.objects.all()
        
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name)
        
        # Filter by specific month
        month_str = self.request.query_params.get("month")
        if month_str:
            month_date = parse_date(month_str)
            if month_date:
                # Ensure it's the first day of the month
                month_date = date(month_date.year, month_date.month, 1)
                qs = qs.filter(progress_month=month_date)
        
        # Filter by date range (from start month to current month)
        start_month_str = self.request.query_params.get("start_month")
        end_month_str = self.request.query_params.get("end_month")
        
        if start_month_str:
            start_date = parse_date(start_month_str)
            if start_date:
                start_date = date(start_date.year, start_date.month, 1)
                qs = qs.filter(progress_month__gte=start_date)
        
        if end_month_str:
            end_date = parse_date(end_month_str)
            if end_date:
                end_date = date(end_date.year, end_date.month, 1)
                qs = qs.filter(progress_month__lte=end_date)
        
        # If no date filters, default to current month and earlier
        if not start_month_str and not end_month_str and not month_str:
            today = date.today()
            current_month = date(today.year, today.month, 1)
            qs = qs.filter(progress_month__lte=current_month)
        
        return qs.order_by("project_name", "progress_month")
    
    def _check_billing_engineer_permission(self, request, action_name="perform this action"):
        """
        Check if user has Billing Site Engineer or PMC Head role.
        Returns (is_allowed, error_response) tuple.
        """
        role = _get_role_from_request(request)
        if role not in ["Billing Site Engineer", "PMC Head"]:
            return False, Response(
                {"detail": f"Only Billing Site Engineer or PMC Head can {action_name} (role='Billing Site Engineer' or 'PMC Head')."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return True, None
    
    @swagger_auto_schema(
        operation_description="List all Project Progress Status records. Filter by project_name, month, start_month, and end_month.",
        manual_parameters=[
            openapi.Parameter('project_name', openapi.IN_QUERY, description="Filter by project name (case-insensitive partial match)", type=openapi.TYPE_STRING),
            openapi.Parameter('month', openapi.IN_QUERY, description="Filter by specific month (YYYY-MM-01)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('start_month', openapi.IN_QUERY, description="Filter from this month onwards (YYYY-MM-01)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter('end_month', openapi.IN_QUERY, description="Filter up to this month (YYYY-MM-01)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: Billing Site Engineer | PMC Head",
                type=openapi.TYPE_STRING,
                required=False
            ),
            openapi.Parameter(
                'X-Role',
                openapi.IN_HEADER,
                description="User role header: Billing Site Engineer | PMC Head",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ProjectProgressStatusSerializer(many=True), 403: "Forbidden"}
    )
    def list(self, request, *args, **kwargs):
        """List all project progress records (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "view project progress")
        if not is_allowed:
            return error_response
        
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Create a new Project Progress Status record. One record per project per month.",
        request_body=_progress_create_schema,
        responses={201: ProjectProgressStatusSerializer, 400: "Bad Request - Validation errors", 403: "Forbidden"}
    )
    def create(self, request, *args, **kwargs):
        """Create project progress record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "create project progress")
        if not is_allowed:
            return error_response
        
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        progress = serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(
            self.get_serializer(progress).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @swagger_auto_schema(
        operation_description="Retrieve a single Project Progress Status record by ID.",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="User role: Billing Site Engineer | PMC Head",
                type=openapi.TYPE_STRING,
                required=False
            ),
            openapi.Parameter(
                'X-Role',
                openapi.IN_HEADER,
                description="User role header: Billing Site Engineer | PMC Head",
                type=openapi.TYPE_STRING,
                required=False
            ),
        ],
        responses={200: ProjectProgressStatusSerializer, 403: "Forbidden", 404: "Not Found"}
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve single project progress record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "view project progress")
        if not is_allowed:
            return error_response
        
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Update a Project Progress Status record (full update). Use PATCH for partial update.",
        request_body=_progress_update_schema,
        responses={200: ProjectProgressStatusSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def update(self, request, *args, **kwargs):
        """Update project progress record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "update project progress")
        if not is_allowed:
            return error_response
        
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_description="Partially update a Project Progress Status record.",
        request_body=_progress_update_schema,
        responses={200: ProjectProgressStatusSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update project progress record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "update project progress")
        if not is_allowed:
            return error_response
        
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_description="Delete a Project Progress Status record.",
        responses={204: "No Content", 403: "Forbidden", 404: "Not Found"}
    )
    def destroy(self, request, *args, **kwargs):
        """Delete project progress record (Billing Site Engineer only)"""
        is_allowed, error_response = self._check_billing_engineer_permission(request, "delete project progress")
        if not is_allowed:
            return error_response
        
        return super().destroy(request, *args, **kwargs)
