from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.contrib.auth.models import User, AnonymousUser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import DailyProgressReport, DPRActivity
from projects.models import Project
from .serializers import DailyProgressReportSerializer, DPRActivitySerializer
from services.notifications import notify_dpr_submitted, notify_dpr_approved, notify_dpr_rejected, notify_dpr_approved_by_role, notify_dpr_rejected_by_role
from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from accounts.rbac_checks import (
    enforce_instance_write,
    enforce_project_write_by_name,
    site_engineer_cannot_delete_approved_dpr,
)
from core.cache_keys import build_rbac_list_cache_key
from monthly_scope.services import ScopeProgressService

import logging
logger = logging.getLogger(__name__)


def safe_cache_delete_pattern(pattern):
    """
    Safely invalidate DPR list caches across LocMem and Redis backends.

    Prefers tag/version bump (and batch coalescing when inside
    ``batch_cache_invalidation``) over delete_pattern.
    """
    prefix = pattern.rstrip("*").rstrip(":")
    if prefix in {"dpr_list", "dpr_pending_approval", "dpr_rejected"}:
        from core.cache_tags import invalidate_tags

        # reports tag covers DPR prefixes; also bump exact prefix for safety.
        invalidate_tags("reports", prefix)
        return
    try:
        if isinstance(cache, LocMemCache):
            return
        cache.delete_pattern(pattern)
    except AttributeError:
        pass


class DailyProgressReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Daily Progress Report CRUD operations

    Supports filtering by project_name and date.
    Requires JWT authentication and project-scoped RBAC.

    **Filtering Parameters:**
    - `project_name`: Filter by project name (case-insensitive partial match)
    - `date`: Filter by exact report date (YYYY-MM-DD)
    - `date_from`: Filter reports from this date onwards
    - `date_to`: Filter reports up to this date
    - `page`: Page number for pagination
    """
    queryset = DailyProgressReport.objects.all()
    serializer_class = DailyProgressReportSerializer
    pagination_class = PageNumberPagination
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.ENGINEERING

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
        cache_key = build_rbac_list_cache_key("dpr_list", request)
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, 300)  # 5 minutes
        return response

    def get_queryset(self):
        """
        Override to add filtering support
        Query params:
        - project_name: Filter by project name (case-insensitive partial match)
        - date: Filter by report_date (exact match or date range)
        - date_from: Filter reports from this date onwards
        - date_to: Filter reports up to this date
        """
        queryset = DailyProgressReport.objects.select_related(
            "submitted_by", "approved_by", "rejected_by"
        ).prefetch_related(
            "activities__scope",
            "activities__scope__category",
            "activities__scope__subcategory"
        ).only(
            "id", "project_name", "job_no", "report_date", "unresolved_issues", "pending_letters",
            "quality_status", "next_day_incident", "bill_status", "gfc_status", "issued_by",
            "designation", "status", "submitted_by__username", "current_approver_role",
            "rejection_reason", "rejected_by__username", "approved_by__username", "approved_at",
            "created_at", "updated_at"
        )

        # Filter by project_name
        project_name = self.request.query_params.get('project_name', None)
        if project_name:
            queryset = queryset.filter(project_name__icontains=project_name.strip())

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
        queryset = queryset.order_by('-report_date', '-created_at')
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            queryset = filter_queryset_by_project_access(
                queryset, user, project_name_field="project_name"
            )
        return queryset

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
    def perform_create(self, serializer):
        super().perform_create(serializer)
        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

    def create(self, request, *args, **kwargs):
        """
        Create a new Daily Progress Report with nested activities.

        **Example Request:**
        ```json
        {
            "project_name": "Thane Project",
            "job_no": "JP001",
            "report_date": "2026-05-10",
            "issued_by": "Site Engineer",
            "designation": "Engineer",
            "activities": [
                {
                    "scope": 3,
                    "executed_quantity": 5.00,
                    "next_day_planned_work": "Continue foundation work",
                    "remarks": "Foundation work completed successfully"
                }
            ]
        }
        ```
        """
        from rest_framework.exceptions import APIException, ValidationError as DRFValidationError

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            project_name = (
                serializer.validated_data.get("project_name")
                or request.data.get("project_name")
            )
            enforce_project_write_by_name(
                request.user, project_name, RBACDomain.ENGINEERING
            )
            instance = serializer.save()
        except (APIException, DRFValidationError):
            # Let DRF / FriendlyAPIErrorMiddleware format these correctly
            raise
        except Exception as e:
            logger.exception("DPR create failed for project=%s", project_name)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while creating the DPR",
                    "errors": [
                        {
                            "field": "non_field_errors",
                            "message": str(e) or "Unexpected error while saving the DPR.",
                        }
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = self.get_success_headers(serializer.data)

        # Trigger notification if DPR was created directly in a pending state
        # (some frontends may bypass the separate /submit/ endpoint)
        pending_statuses = [
            DailyProgressReport.Status.PENDING_TEAM_LEAD,
            DailyProgressReport.Status.PENDING_COORDINATOR,
            DailyProgressReport.Status.PENDING_PMC_HEAD,
        ]

        if instance.status in pending_statuses:
            logger.info(
                "DPR created directly in pending state (%s). Triggering notification.",
                instance.status,
            )
            try:
                notify_dpr_submitted(instance)
            except Exception as notify_err:
                logger.error(
                    "Failed to send notification after direct DPR create: %s",
                    notify_err,
                )

        activities_added = getattr(instance, "_activities_added", None)
        if activities_added is not None:
            response_data = {
                "success": True,
                "message": "Activities added to existing DPR",
                "dpr_id": instance.id,
                "activities_added": activities_added,
                "dpr": serializer.data,
            }
            return Response(response_data, status=status.HTTP_200_OK, headers=headers)

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @swagger_auto_schema(
        operation_description="Update a Daily Progress Report (full update). Use PATCH for partial update.",
        request_body=DailyProgressReportSerializer,
        responses={200: DailyProgressReportSerializer}
    )
    def perform_update(self, serializer):
        super().perform_update(serializer)
        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

    def update(self, request, *args, **kwargs):
        """
        Update a Daily Progress Report (full update).
        Use PATCH method for partial updates.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        enforce_instance_write(request.user, instance, RBACDomain.ENGINEERING)
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
    def perform_destroy(self, instance):
        # Capture scopes before CASCADE deletes activities
        scope_ids = list(
            instance.activities.exclude(scope_id=None).values_list("scope_id", flat=True)
        )
        super().perform_destroy(instance)
        ScopeProgressService.recalculate_scopes(scope_ids)
        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

    def destroy(self, request, *args, **kwargs):
        """
        Delete a Daily Progress Report.
        All associated activities will also be deleted (CASCADE).
        """
        instance = self.get_object()
        enforce_instance_write(request.user, instance, RBACDomain.ENGINEERING)
        site_engineer_cannot_delete_approved_dpr(request.user, instance)
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
        activities = dpr.activities.select_related(
            'scope',
            'scope__category',
            'scope__subcategory'
        ).all()
        serializer = DPRActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Submit DPR for approval with optional activities",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the submitter (Site Engineer)'),
                'activities': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'date': openapi.Schema(type=openapi.TYPE_STRING, format='date'),
                            'activity': openapi.Schema(type=openapi.TYPE_STRING),
                            'deliverables': openapi.Schema(type=openapi.TYPE_STRING),
                            'target_achieved': openapi.Schema(type=openapi.TYPE_NUMBER),
                            'next_day_plan': openapi.Schema(type=openapi.TYPE_STRING),
                            'remarks': openapi.Schema(type=openapi.TYPE_STRING)
                        }
                    ),
                    description='Optional list of activities to add/update'
                )
            }
        ),
        responses={200: DailyProgressReportSerializer, 400: 'Validation Error'}
    )
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """
        Submit DPR for approval workflow.

        **Endpoint:** POST /api/dpr/{id}/submit/

        Submits the DPR to the approval workflow.
        Site Engineer submits -> goes to Team Lead

        Optionally accepts activities to add/update before submission.
        """
        dpr = self.get_object()

        # FIXED: Safe project lookup using ID
        project_id = request.data.get('project')
        if project_id is not None:
            try:
                # Use pk/id for unique lookup instead of name
                project = Project.objects.get(pk=project_id)
                # Use project as needed (e.g., validation, logging, etc.)
                # For example: validate dpr.project_name matches project.name
            except ObjectDoesNotExist:
                return Response(
                    {'error': f'Project with id {project_id} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except MultipleObjectsReturned:
                # This shouldn't happen with pk lookup, but handle it
                return Response(
                    {'error': 'Multiple projects found with the same id (data corruption)'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            except ValueError:
                return Response(
                    {'error': 'Invalid project id format'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        role = request.data.get('role', 'Site Engineer')
        activities_data = request.data.get('activities', [])

        # Only allow submission from draft or rejected status
        if dpr.status not in [DailyProgressReport.Status.DRAFT, DailyProgressReport.Status.REJECTED]:
            return Response(
                {'error': 'DPR can only be submitted from draft or rejected status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        is_resubmit = dpr.status == DailyProgressReport.Status.REJECTED

        try:
            with transaction.atomic():
                # Handle activities if provided (scope-based model)
                if activities_data:
                    if not isinstance(activities_data, list):
                        return Response(
                            {'error': 'activities must be a list'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    activity_serializer = DPRActivitySerializer(
                        data=activities_data, many=True
                    )
                    if not activity_serializer.is_valid():
                        return Response(
                            {
                                "success": False,
                                "message": "Validation failed",
                                "errors": activity_serializer.errors,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    for activity_data in activity_serializer.validated_data:
                        scope = activity_data.get("scope")
                        if not scope:
                            continue
                        existing_activity = DPRActivity.objects.filter(
                            dpr=dpr, scope=scope
                        ).first()
                        if existing_activity:
                            existing_activity.executed_quantity = activity_data.get(
                                "executed_quantity", existing_activity.executed_quantity
                            )
                            existing_activity.next_day_planned_work = activity_data.get(
                                "next_day_planned_work",
                                existing_activity.next_day_planned_work,
                            )
                            existing_activity.remarks = activity_data.get(
                                "remarks", existing_activity.remarks
                            )
                            existing_activity.save()
                        else:
                            activity = DPRActivity(dpr=dpr, **activity_data)
                            activity.save()

                # Update DPR status and submitter BEFORE progress recalc so
                # draft → pending quantities are included in the cumulative SUM.
                dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
                dpr.submitted_by = request.user
                dpr.current_approver_role = 'Team Leader'
                dpr.rejection_reason = ''  # Clear rejection reason on resubmission
                dpr.rejected_by = None
                dpr.save()

                ScopeProgressService.recalculate_for_dpr(dpr)

                # Cache invalidation (before commit — version bump is cheap)
                safe_cache_delete_pattern("dpr_list:*")
                safe_cache_delete_pattern("dpr_pending_approval:*")
                safe_cache_delete_pattern("dpr_rejected:*")

                # Notifications: WebSocket sync + email via ThreadPoolExecutor on_commit
                logger.info(
                    "DPR submitted successfully dpr_id=%s project=%s resubmit=%s",
                    dpr.id,
                    dpr.project_name,
                    is_resubmit,
                )
                notify_dpr_submitted(dpr, is_resubmit=is_resubmit)

                serializer = self.get_serializer(dpr)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("DPR submit failed for dpr_id=%s", dpr.id)
            return Response(
                {
                    "success": False,
                    "message": "Submission failed",
                    "errors": [
                        {
                            "field": "non_field_errors",
                            "message": str(e) or "Unexpected error while submitting the DPR.",
                        }
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        Team Lead approves DPR and sends to PMC Manager.
        
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
        dpr.current_approver_role = 'PMC Manager'
        dpr.save()
        ScopeProgressService.recalculate_for_dpr(dpr)

        # Send approval notification to submitter (Site Engineer)
        notify_dpr_approved_by_role(dpr, 'Team Leader')

        # Send submission notification to next approver (PMC Manager)
        notify_dpr_submitted(dpr)

        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="PMC Manager approves DPR",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'role': openapi.Schema(type=openapi.TYPE_STRING, description='Role of the approver (PMC Manager)')
            }
        ),
        responses={200: DailyProgressReportSerializer}
    )
    @action(detail=True, methods=['post'])
    def approve_coordinator(self, request, pk=None):
        """
        PMC Manager approves DPR and sends to PMC Head.
        
        **Endpoint:** POST /api/dpr/{id}/approve_coordinator/
        (URL kept for frontend compatibility)
        """
        dpr = self.get_object()
        
        if dpr.status != DailyProgressReport.Status.PENDING_COORDINATOR:
            return Response(
                {'error': 'DPR is not pending PMC Manager approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update DPR status
        dpr.status = DailyProgressReport.Status.PENDING_PMC_HEAD
        dpr.current_approver_role = 'PMC Head'
        dpr.save()
        ScopeProgressService.recalculate_for_dpr(dpr)

        # Send approval notification to Team Lead and Site Engineer
        notify_dpr_approved_by_role(dpr, 'PMC Manager')

        # Send submission notification to next approver (PMC Head)
        notify_dpr_submitted(dpr)

        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

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
        ScopeProgressService.recalculate_for_dpr(dpr)

        # Send final approval notification to Coordinator, Team Lead, and Site Engineer
        notify_dpr_approved_by_role(dpr, 'PMC Head')

        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

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
        rejected_by_role = None
        if dpr.status == DailyProgressReport.Status.PENDING_TEAM_LEAD:
            # Team Lead rejects -> send back to Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
            rejected_by_role = 'Team Leader'
        elif dpr.status == DailyProgressReport.Status.PENDING_COORDINATOR:
            # PMC Manager rejects -> send back to Team Lead and Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
            rejected_by_role = 'PMC Manager'
        elif dpr.status == DailyProgressReport.Status.PENDING_PMC_HEAD:
            # PMC Head rejects -> send back to PMC Manager, Team Lead, and Site Engineer
            dpr.status = DailyProgressReport.Status.REJECTED
            dpr.current_approver_role = ''
            rejected_by_role = 'PMC Head'
        else:
            return Response(
                {'error': 'DPR is not in a rejectable status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update rejection details
        dpr.rejection_reason = rejection_reason
        dpr.rejected_by = request.user
        dpr.save()
        ScopeProgressService.recalculate_for_dpr(dpr)

        # Send rejection notification to appropriate recipients
        if rejected_by_role:
            notify_dpr_rejected_by_role(dpr, rejected_by_role)

        # Cache invalidation
        safe_cache_delete_pattern("dpr_list:*")
        safe_cache_delete_pattern("dpr_pending_approval:*")
        safe_cache_delete_pattern("dpr_rejected:*")

        serializer = self.get_serializer(dpr)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Get DPRs pending approval for a specific role",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="Role to filter by (Team Leader, PMC Manager, PMC Head)",
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
        role = request.query_params.get('role', None).strip() if request.query_params.get('role') else None

        if not role:
            return Response(
                {'error': 'Role parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        cache_key = build_rbac_list_cache_key(
            "dpr_pending_approval",
            request,
            extra_parts=[f"role:{role}"],
            use_query_string=False,
        )
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        # Map role to status (Coordinator kept as legacy alias of PMC Manager)
        role_status_map = {
            'Team Leader': DailyProgressReport.Status.PENDING_TEAM_LEAD,
            'PMC Manager': DailyProgressReport.Status.PENDING_COORDINATOR,
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
        ).prefetch_related(
            'activities__scope',
            'activities__scope__category',
            'activities__scope__subcategory'
        ).order_by('-report_date', '-created_at')

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)

    @swagger_auto_schema(
        operation_description="Get rejected DPRs for a specific role",
        manual_parameters=[
            openapi.Parameter(
                'role',
                openapi.IN_QUERY,
                description="Role to filter by (Team Leader, PMC Manager, PMC Head)",
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
        role = request.query_params.get('role', None).strip() if request.query_params.get('role') else None

        if not role:
            return Response(
                {'error': 'Role parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        cache_key = build_rbac_list_cache_key(
            "dpr_rejected",
            request,
            extra_parts=[f"role:{role}"],
            use_query_string=False,
        )
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        # Get all rejected DPRs
        queryset = DailyProgressReport.objects.filter(
            status=DailyProgressReport.Status.REJECTED
        ).prefetch_related(
            'activities__scope',
            'activities__scope__category',
            'activities__scope__subcategory'
        ).order_by('-report_date', '-created_at')

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        cache.set(cache_key, data, 300)  # 5 minutes
        return Response(data)
