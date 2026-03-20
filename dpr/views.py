from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db.models import Q
from django.utils.dateparse import parse_date
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import DailyProgressReport, DPRActivity
from .serializers import DailyProgressReportSerializer, DPRActivitySerializer


class DailyProgressReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Daily Progress Report CRUD operations
    
    Supports filtering by project_name and date.
    No authentication required for testing.
    
    **Filtering Parameters:**
    - `project_name`: Filter by project name (case-insensitive partial match)
    - `date`: Filter by exact report date (YYYY-MM-DD)
    - `date_from`: Filter reports from this date onwards
    - `date_to`: Filter reports up to this date
    - `page`: Page number for pagination
    """
    queryset = DailyProgressReport.objects.all()
    serializer_class = DailyProgressReportSerializer
    permission_classes = [AllowAny]  # No authentication required for testing

    @swagger_auto_schema(
        operation_description="List all Daily Progress Reports with optional filtering",
        manual_parameters=[
            openapi.Parameter(
                'project_name',
                openapi.IN_QUERY,
                description="Filter by project name (case-insensitive partial match)",
                type=openapi.TYPE_STRING,
                required=False
            ),
            openapi.Parameter(
                'date',
                openapi.IN_QUERY,
                description="Filter by exact report date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'date_from',
                openapi.IN_QUERY,
                description="Filter reports from this date onwards (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'date_to',
                openapi.IN_QUERY,
                description="Filter reports up to this date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'page',
                openapi.IN_QUERY,
                description="Page number for pagination",
                type=openapi.TYPE_INTEGER,
                required=False
            ),
        ],
        responses={200: DailyProgressReportSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Override to add filtering support
        Query params:
        - project_name: Filter by project name (case-insensitive partial match)
        - date: Filter by report_date (exact match or date range)
        - date_from: Filter reports from this date onwards
        - date_to: Filter reports up to this date
        """
        queryset = DailyProgressReport.objects.all()
        
        # Filter by project_name
        project_name = self.request.query_params.get('project_name', None)
        if project_name:
            queryset = queryset.filter(project_name__icontains=project_name)
        
        # Filter by exact date
        date = self.request.query_params.get('date', None)
        if date:
            try:
                date_obj = parse_date(date)
                if date_obj:
                    queryset = queryset.filter(report_date=date_obj)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        
        # Filter by date range
        date_from = self.request.query_params.get('date_from', None)
        if date_from:
            try:
                date_from_obj = parse_date(date_from)
                if date_from_obj:
                    queryset = queryset.filter(report_date__gte=date_from_obj)
            except (ValueError, TypeError):
                pass
        
        date_to = self.request.query_params.get('date_to', None)
        if date_to:
            try:
                date_to_obj = parse_date(date_to)
                if date_to_obj:
                    queryset = queryset.filter(report_date__lte=date_to_obj)
            except (ValueError, TypeError):
                pass
        
        # Order by latest first (handled in model Meta, but ensuring here too)
        return queryset.order_by('-report_date', '-created_at')

    @swagger_auto_schema(
        operation_description="Retrieve a single Daily Progress Report by ID",
        responses={200: DailyProgressReportSerializer}
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_description="Create a new Daily Progress Report with nested activities",
        request_body=DailyProgressReportSerializer,
        responses={201: DailyProgressReportSerializer}
    )
    def create(self, request, *args, **kwargs):
        """
        Create a new Daily Progress Report with nested activities.
        
        **Example Request:**
        ```json
        {
            "project_name": "Highway Construction Project",
            "job_no": "JOB-2024-001",
            "report_date": "2024-01-15",
            "issued_by": "John Doe",
            "designation": "Site Engineer",
            "activities": [
                {
                    "date": "2024-01-15",
                    "activity": "Foundation excavation",
                    "target_achieved": 85.5
                }
            ]
        }
        ```
        """
        try:
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {
                        'error': 'Validation failed',
                        'details': serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED,
                headers=headers
            )
        except Exception as e:
            return Response(
                {
                    'error': 'An error occurred while creating the DPR',
                    'message': str(e),
                    'details': getattr(e, 'detail', None) or str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @swagger_auto_schema(
        operation_description="Update a Daily Progress Report (full update). Use PATCH for partial update.",
        request_body=DailyProgressReportSerializer,
        responses={200: DailyProgressReportSerializer}
    )
    def update(self, request, *args, **kwargs):
        """
        Update a Daily Progress Report (full update).
        Use PATCH method for partial updates.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Delete a Daily Progress Report",
        responses={
            200: openapi.Response(
                description="Success",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'message': openapi.Schema(type=openapi.TYPE_STRING, description='Success message')
                    }
                )
            ),
            404: "Not Found - DPR does not exist"
        }
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a Daily Progress Report.
        All associated activities will also be deleted (CASCADE).
        """
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {'message': 'Daily Progress Report deleted successfully'},
            status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        operation_description="Get all activities for a specific Daily Progress Report",
        responses={200: DPRActivitySerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def activities(self, request, pk=None):
        """
        Get all activities for a specific DPR.
        
        **Endpoint:** GET /api/dpr/{id}/activities/
        
        Returns a list of all activities associated with the DPR.
        """
        dpr = self.get_object()
        activities = dpr.activities.all()
        serializer = DPRActivitySerializer(activities, many=True)
        return Response(serializer.data)
