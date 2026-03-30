from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.utils import timezone
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

    @swagger_auto_schema(
        operation_description="Submit DPR for approval",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the user submitting (Site Engineer, Billing Site Engineer, QAQC Site Engineer)')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """
        Submit DPR for approval workflow.
        
        **Endpoint:** POST /api/dpr/{id}/submit/
        
        Submits the DPR to the approval workflow.
        Site Engineer submits -> goes to Team Lead
        """
        dpr = self.get_object()
        role = request.data.get('role', 'Site Engineer')
        
        # Only allow submission from draft or rejected status
        if dpr.status not in [DailyProgressReport.Status.DRAFT, DailyProgressReport.Status.REJECTED]:
            return Response(
                {'error': 'DPR can only be submitted from draft or rejected status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update DPR status and submitter
        dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        dpr.submitted_by = request.user
        dpr.current_approver_role = 'Team Leader'
        dpr.rejection_reason = ''  # Clear rejection reason on resubmission
        dpr.rejected_by = None
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Team Lead approves DPR",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the approver (Team Leader)')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def approve_team_lead(self, request, pk=None):
        """
        Team Lead approves DPR and sends to Coordinator.
        
        **Endpoint:** POST /api/dpr/{id}/approve_team_lead/
        """
        dpr = self.get_object()
        
        if dpr.status != DailyProgressReport.Status.PENDING_TEAM_LEAD:
            return Response(
                {'error': 'DPR is not pending Team Lead approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update DPR status
        dpr.status = DailyProgressReport.Status.PENDING_COORDINATOR
        dpr.current_approver_role = 'Coordinator'
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Coordinator approves DPR",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the approver (Coordinator)')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def approve_coordinator(self, request, pk=None):
        """
        Coordinator approves DPR and sends to PMC Head.
        
        **Endpoint:** POST /api/dpr/{id}/approve_coordinator/
        """
        dpr = self.get_object()
        
        if dpr.status != DailyProgressReport.Status.PENDING_COORDINATOR:
            return Response(
                {'error': 'DPR is not pending Coordinator approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update DPR status
        dpr.status = DailyProgressReport.Status.PENDING_PMC_HEAD
        dpr.current_approver_role = 'PMC Head'
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="PMC Head approves DPR",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the approver (PMC Head)')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def approve_pmc_head(self, request, pk=None):
        """
        PMC Head gives final approval to DPR.
        
        **Endpoint:** POST /api/dpr/{id}/approve_pmc_head/
        """
        dpr = self.get_object()
        
        if dpr.status != DailyProgressReport.Status.PENDING_PMC_HEAD:
            return Response(
                {'error': 'DPR is not pending PMC Head approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update DPR status to approved
        dpr.status = DailyProgressReport.Status.APPROVED
        dpr.approved_by = request.user
        dpr.approved_at = timezone.now()
        dpr.current_approver_role = ''
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Reject DPR",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['rejection_reason'],
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the rejector'),
                'rejection_reason': openapi.Schema(type=openapi.TYPE_STRING, description='Reason for rejection')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """
        Reject DPR and send back to lower roles with rejection reason.
        
        **Endpoint:** POST /api/dpr/{id}/reject/
        
        When rejected by a role, the DPR is sent back to all lower roles
        with the rejection reason, and finally to the Site Engineer for modification.
        """
        dpr = self.get_object()
        rejection_reason = request.data.get('rejection_reason', '')
        
        if not rejection_reason:
            return Response(
                {'error': 'Rejection reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Determine which role is rejecting and set appropriate status
        if dpr.status == DailyProgressReport.Status.PENDING_TEAM_LEAD:
            # Team Lead rejects -> send back to Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
        elif dpr.status == DailyProgressReport.Status.PENDING_COORDINATOR:
            # Coordinator rejects -> send back to Team Lead and Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
        elif dpr.status == DailyProgressReport.Status.PENDING_PMC_HEAD:
            # PMC Head rejects -> send back to Coordinator, Team Lead, and Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
        else:
            return Response(
                {'error': 'DPR is not in a rejectable status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update rejection details
        dpr.rejection_reason = rejection_reason
        dpr.rejected_by = request.user
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Get DPRs pending approval for a specific role",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="Role to filter by (Team Leader, Coordinator, PMC Head)",
                type=openapi.TYPE_STRING,
                required=True
            ),
        ],
        responses={200: DailyProgressReportSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def pending_approval(self, request):
        """
        Get all DPRs pending approval for a specific role.
        
        **Endpoint:** GET /api/dpr/pending_approval/?role=Team Leader
        
        Returns DPRs that are waiting for approval from the specified role.
        """
        role = request.query_params.get('role', None)
        
        if not role:
            return Response(
                {'error': 'Role parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Map role to status
        role_status_map = {
            'Team Leader': DailyProgressReport.Status.PENDING_TEAM_LEAD,
            'Coordinator': DailyProgressReport.Status.PENDING_COORDINATOR,
            'PMC Head': DailyProgressReport.Status.PENDING_PMC_HEAD,
        }
        
        if role not in role_status_map:
            return Response(
                {'error': f'Invalid role. Must be one of: {", ".join(role_status_map.keys())}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get DPRs pending for the specified role
        queryset = DailyProgressReport.objects.filter(
            status=role_status_map[role]
        ).order_by('-report_date', '-created_at')
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Get rejected DPRs for a specific role",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="Role to filter by (Team Leader, Coordinator, PMC Head)",
                type=openapi.TYPE_STRING,
                required=True
            ),
        ],
        responses={200: DailyProgressReportSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def rejected(self, request):
        """
        Get all rejected DPRs that need to be reviewed by a specific role.
        
        **Endpoint:** GET /api/dpr/rejected/?role=Team Leader
        
        When a DPR is rejected by a higher role, it's sent back to all lower roles.
        This endpoint returns DPRs that were rejected and need review by the specified role.
        """
        role = request.query_params.get('role', None)
        
        if not role:
            return Response(
                {'error': 'Role parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get all rejected DPRs
        queryset = DailyProgressReport.objects.filter(
            status=DailyProgressReport.Status.REJECTED
        ).order_by('-report_date', '-created_at')
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
