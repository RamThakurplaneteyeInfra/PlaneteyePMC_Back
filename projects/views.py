from datetime import datetime
from typing import List, Dict, Any

import pandas as pd
from django.contrib.auth.models import User
from django.db.models import Prefetch, Q
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.rbac import RBACDomain, get_user_assigned_projects_qs, is_admin_user
from accounts.permissions import IsAuthenticatedProjectRBAC
from project_dates.eot_models import ProjectEOT

from .models import Project, ProjectDashboardData, Site, ProjectLog, ProjectLogEntry
from .serializers import (
    ProjectDashboardDataSerializer,
    ProjectInitSerializer,
    ProjectSerializer,
    SiteSerializer,
    ProjectLogSerializer,
)


def _active_eots_prefetch() -> Prefetch:
    return Prefetch(
        "eots",
        queryset=ProjectEOT.objects.filter(is_active=True)
        .select_related(
            "created_by",
            "updated_by",
            "project_dates",
            "project_dates__contractor",
        )
        .order_by("-eot_number", "-id"),
    )


def _scl_project_dates_prefetch() -> Prefetch:
    from project_dates.models import ProjectDates

    return Prefetch(
        "project_dates",
        queryset=ProjectDates.objects.filter(date_type=ProjectDates.DATE_TYPE_SCL)
        .select_related("contractor")
        .only(
            "id",
            "project_id",
            "date_type",
            "contract_finish",
            "project_start",
            "forecast_finish",
            "eot_date",
            "contractor_id",
            "contractor_name",
            "contractor__id",
            "contractor__contractor_name",
        ),
        to_attr="_prefetched_scl_dates",
    )

class ProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing projects with role-based access and team assignments.

    Performance Notes:
    - Uses select_related for dashboard_data and user fields
    - Uses prefetch_related for many-to-many relationships (coordinators, site_engineers)
    """
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.GENERAL
    search_fields = ["name", "client_name", "location", "description"]
    ordering_fields = ["name", "created_at", "status", "commencement_date"]
    ordering = ["-created_at"]

    def update(self, request, *args, **kwargs):
        from accounts.rbac_checks import assert_project_writable

        assert_project_writable(self.get_object())
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        from accounts.rbac_checks import assert_project_writable

        assert_project_writable(self.get_object())
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        """
        Get filtered queryset based on user role and permissions.

        Performance optimized with select_related and prefetch_related to avoid N+1 queries.
        """
        # Swagger / OpenAPI schema generation runs without a real user
        if getattr(self, "swagger_fake_view", False):
            return Project.objects.none()

        base_queryset = Project.objects.select_related(
            'dashboard_data',
            'pmc_head',
            'team_lead',
            'site_engineer',
            'billing_site_engineer',
            'qaqc_site_engineer',
            'hse_site_engineer',
            'created_by'
        ).prefetch_related(
            'sites',
            'coordinators',
            'site_engineers',
            'assigned_users',
            _active_eots_prefetch(),
            _scl_project_dates_prefetch(),
        )

        user = self.request.user
        if not user.is_authenticated:
            qs = base_queryset
        elif is_admin_user(user):
            qs = base_queryset
        else:
            qs = get_user_assigned_projects_qs(user).select_related(
                'dashboard_data',
                'pmc_head',
                'team_lead',
                'site_engineer',
                'billing_site_engineer',
                'qaqc_site_engineer',
                'hse_site_engineer',
                'created_by',
            ).prefetch_related(
                'sites',
                'coordinators',
                'site_engineers',
                'assigned_users',
                _active_eots_prefetch(),
                _scl_project_dates_prefetch(),
            )

        # Hide merged duplicates from normal lists/dropdowns unless explicitly requested.
        include_merged = str(
            self.request.query_params.get("include_merged", "")
        ).lower() in {"1", "true", "yes"}
        if not include_merged:
            qs = qs.exclude(status="merged")

        # Optional status filter (comma-separated). Used by frontend dropdowns.
        status_param = (self.request.query_params.get("status") or "").strip()
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]
            if statuses:
                qs = qs.filter(status__in=statuses)

        billing_param = (self.request.query_params.get("billing_status") or "").strip()
        if billing_param:
            from projects.services.project_completion import normalize_billing_status

            billing_values = []
            for raw in billing_param.split(","):
                normalized = normalize_billing_status(raw)
                if normalized:
                    billing_values.append(normalized)
            if billing_values:
                qs = qs.filter(billing_status__in=billing_values)

        return qs.order_by("-created_at", "name")

    def _has_group_permission(self, user, group_names: List[str]) -> bool:
        """Check if user has any of the specified groups or is superuser."""
        return user.groups.filter(name__in=group_names).exists() or user.is_superuser

    def _get_user_by_id_safe(self, user_id: int) -> User:
        """Safely get user by ID, raise ValidationError if not found."""
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'error': 'User not found'})

    def _validate_user_role(self, user: User, required_groups: List[str], error_message: str):
        """Validate that user has required role."""
        if not user.groups.filter(name__in=required_groups).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(error_message)

    def _check_assignment_permission(self, user: User, project: Project, allowed_roles: List[str], allowed_users: List = None) -> bool:
        """Check if user can assign team members to project."""
        if self._has_group_permission(user, allowed_roles):
            return True
        if allowed_users and any(getattr(project, attr) == user for attr in allowed_users):
            return True
        return False

    def perform_create(self, serializer):
        """Set creator, default status to active, auto-assign pmc_head if applicable."""
        user = self.request.user
        save_kwargs = {"created_by": user}
        # New projects must show in active dropdowns unless caller sets another status.
        if not serializer.validated_data.get("status"):
            save_kwargs["status"] = "active"
        if is_admin_user(user):
            save_kwargs["pmc_head"] = user
        project = serializer.save(**save_kwargs)
        from core.business_audit import write_business_audit
        from core.models import BusinessAuditLog

        write_business_audit(
            entity_type=BusinessAuditLog.ENTITY_PROJECT,
            action=BusinessAuditLog.ACTION_CREATED,
            actor=user,
            entity_id=project.pk,
            project=project,
            detail=f"Project '{project.name}' created",
        )

    @action(detail=False, methods=["get"], url_path="dropdown")
    def dropdown(self, request):
        """
        Lightweight project list for UI dropdowns (no pagination).

        GET /api/projects/dropdown/
        GET /api/projects-data/projects/dropdown/?status=active

        Returns every project the caller can access (RBAC), excluding merged
        unless include_merged=true. Avoids PAGE_SIZE=20 truncation that hides
        newly added projects when the client only loads the first page.
        Cached (RBAC-scoped) for CACHE_TTL_DROPDOWN.
        """
        from core.cache_keys import build_rbac_list_cache_key
        from core.cache_ops import TTL_DROPDOWN
        from core.cache_swr import get_or_rebuild

        cache_key = build_rbac_list_cache_key("projects_dropdown", request)

        def _build_dropdown():
            user = request.user
            if is_admin_user(user):
                qs = Project.objects.all()
            else:
                qs = get_user_assigned_projects_qs(user)

            include_merged = str(
                request.query_params.get("include_merged", "")
            ).lower() in {
                "1",
                "true",
                "yes",
            }
            if not include_merged:
                qs = qs.exclude(status="merged")

            status_param = (request.query_params.get("status") or "").strip()
            if status_param:
                statuses = [s.strip() for s in status_param.split(",") if s.strip()]
                if statuses:
                    qs = qs.filter(status__in=statuses)

            billing_param = (request.query_params.get("billing_status") or "").strip()
            if billing_param:
                from projects.services.project_completion import normalize_billing_status

                billing_values = []
                for raw in billing_param.split(","):
                    normalized = normalize_billing_status(raw)
                    if normalized:
                        billing_values.append(normalized)
                if billing_values:
                    qs = qs.filter(billing_status__in=billing_values)

            search = (request.query_params.get("search") or "").strip()
            if search:
                qs = qs.filter(
                    Q(name__icontains=search)
                    | Q(client_name__icontains=search)
                    | Q(location__icontains=search)
                )

            rows = list(
                qs.order_by("name").values(
                    "id", "name", "status", "billing_status", "client_name"
                )
            )
            data = [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "status": row["status"],
                    "billing_status": row["billing_status"] or Project.BILLING_STATUS_PENDING,
                    "client_name": row["client_name"] or "",
                }
                for row in rows
            ]
            return {
                "success": True,
                "message": "Projects retrieved successfully.",
                "count": len(data),
                "data": data,
            }

        payload = get_or_rebuild(
            cache_key,
            _build_dropdown,
            soft_ttl=TTL_DROPDOWN,
            hard_ttl=TTL_DROPDOWN * 2,
            prefix="projects_dropdown",
        )
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        """
        Lightweight PMC dashboard project cards.

        GET /api/projects/overview/
            → all accessible *active* projects (excludes merged/completed/on_hold/planning)

        GET /api/projects/overview/?status=active,planning
            → explicit status filter (merged still excluded unless requested)

        GET /api/projects/overview/?paginate=true&page=1&page_size=20
            → optional paginated response

        Cached (RBAC-scoped, SWR) under prefix ``project_overview_v4``.
        Cache hits skip queryset aggregation and serialization.
        """
        from core.cache_keys import build_rbac_list_cache_key
        from core.cache_ops import TTL_OVERVIEW
        from core.cache_swr import get_or_rebuild
        from projects.serializers_overview import ProjectOverviewSerializer
        from projects.services.project_overview import (
            CACHE_PREFIX,
            ProjectOverviewService,
        )

        paginate = request.query_params.get("paginate", False)
        page = request.query_params.get("page", 1)
        page_size = request.query_params.get("page_size", 20)
        search = request.query_params.get("search", "")
        client = (
            request.query_params.get("client", "")
            or request.query_params.get("client_name", "")
        )
        status_filter = request.query_params.get("status", "")
        billing_status_filter = request.query_params.get("billing_status", "")
        project_type = request.query_params.get("project_type", "")
        project_name = (
            request.query_params.get("project_name", "")
            or request.query_params.get("name", "")
        )
        ordering = (
            request.query_params.get("ordering", "")
            or request.query_params.get("sort", "")
        )

        # Same key shape as ProjectOverviewService (filters + RBAC scope + version).
        truthy = str(paginate or "").strip().lower() in {"1", "true", "yes", "on"}
        try:
            page_i = max(1, int(page))
        except (TypeError, ValueError):
            page_i = 1
        try:
            page_size_i = min(100, max(1, int(page_size)))
        except (TypeError, ValueError):
            page_size_i = 20
        default_ordering = ProjectOverviewService.DEFAULT_ORDERING
        cache_key = build_rbac_list_cache_key(
            CACHE_PREFIX,
            request,
            extra_parts=[
                f"pg{int(truthy)}",
                f"p{page_i}" if truthy else "pall",
                f"ps{page_size_i}" if truthy else "psall",
                f"s{search}",
                f"c{client}",
                f"st{status_filter}",
                f"bs{billing_status_filter}",
                f"pt{project_type}",
                f"pn{project_name}",
                f"o{ordering or default_ordering}",
            ],
            use_query_string=False,
        )

        def _build_overview():
            user = request.user
            if is_admin_user(user):
                qs = Project.objects.all()
            else:
                qs = get_user_assigned_projects_qs(user)

            # Service-level cache disabled — view caches the final serialized body.
            service = ProjectOverviewService(qs, request=request)
            payload = service.get_paginated_overview(
                paginate=paginate,
                page=page,
                page_size=page_size,
                search=search,
                client=client,
                status=status_filter,
                billing_status=billing_status_filter,
                project_type=project_type,
                project_name=project_name,
                ordering=ordering,
                use_cache=False,
            )
            serializer = ProjectOverviewSerializer(payload["data"], many=True)
            # Plain list for Redis/LocMem pickling (avoid ReturnList quirks).
            payload["data"] = list(serializer.data)
            return payload

        payload = get_or_rebuild(
            cache_key,
            _build_overview,
            soft_ttl=TTL_OVERVIEW,
            hard_ttl=TTL_OVERVIEW * 2,
            prefix=CACHE_PREFIX,
        )
        return Response(payload)

    @action(detail=False, methods=['get'])
    def documents(self, request):
        """
        Get project documents for the vault.
        API: GET /api/projects-data/projects/documents/
        Returns all projects that have documentation files uploaded.
        """
        # Preserve RBAC from get_queryset, then reload a lean projection.
        accessible_ids = list(
            self.get_queryset()
            .filter(
                has_documentation=True,
                documentation_file__isnull=False,
            )
            .exclude(documentation_file='')
            .values_list('id', flat=True)
        )
        docs_projects = (
            Project.objects.filter(id__in=accessible_ids)
            .select_related('pmc_head')
            .only(
                'id',
                'name',
                'documentation_file',
                'updated_at',
                'created_at',
                'pmc_head_id',
                'pmc_head__username',
            )
            .order_by('-created_at')
        )

        documents = []
        for project in docs_projects:
            if project.documentation_file:
                file_name = project.documentation_file.name.split('/')[-1]
                file_extension = file_name.split('.')[-1].upper() if '.' in file_name else 'UNKNOWN'

                documents.append({
                    'id': project.id,
                    'project_id': project.id,
                    'project_name': project.name,
                    'file_name': file_name,
                    'file_url': request.build_absolute_uri(project.documentation_file.url),
                    'file_type': file_extension,
                    'uploaded_at': project.updated_at.isoformat() if project.updated_at else None,
                    'uploaded_by': project.pmc_head.username if project.pmc_head else None,
                })

        return Response(documents)

    def _safe_decimal(self, value, default=None) -> float | None:
        """Safely convert value to decimal."""
        if pd.isna(value) or value == '':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _safe_int(self, value, default=0) -> int:
        """Safely convert value to integer."""
        if pd.isna(value) or value == '':
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default

    def _safe_date(self, value, default=None):
        """Safely convert value to date."""
        if pd.isna(value) or value == '':
            return default
        if isinstance(value, str):
            try:
                return parse_date(value)
            except (ValueError, TypeError):
                return default
        if isinstance(value, datetime):
            return value.date()
        return default

    @action(detail=True, methods=['post'], url_path='import-dashboard-data')
    def import_dashboard_data(self, request, pk=None):
        """
        Import dashboard data from Excel file.
        API: POST /api/projects-data/projects/{id}/import-dashboard-data/
        """
        project = self.get_object()
        excel_file = request.FILES.get('file')

        if not excel_file:
            return Response({'error': 'No Excel file provided'}, status=400)

        try:
            # Read Excel file
            df = pd.read_excel(excel_file, engine='openpyxl')

            # Convert column names to lowercase and replace spaces with underscores
            df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

            # Get the first row (assuming single project data per file)
            row = df.iloc[0].to_dict()

            # Map Excel columns to model fields
            dashboard_data, created = ProjectDashboardData.objects.get_or_create(
                project=project,
                defaults={
                    # Financial Metrics
                    'planned_value': self._safe_decimal(row.get('planned_value') or row.get('plannedvalue')),
                    'earned_value': self._safe_decimal(row.get('earned_value') or row.get('earnedvalue')),
                    'bcwp': self._safe_decimal(row.get('bcwp')),
                    'ac': self._safe_decimal(row.get('ac') or row.get('actual_cost')),
                    'actual_billed': self._safe_decimal(row.get('actual_billed') or row.get('actualbilled')),

                    # Contract Values
                    'original_contract_value': self._safe_decimal(row.get('original_contract_value') or row.get('originalcontractvalue')),
                    'approved_vo': self._safe_decimal(row.get('approved_vo') or row.get('approvedvo')),
                    'revised_contract_value': self._safe_decimal(row.get('revised_contract_value') or row.get('revisedcontractvalue')),
                    'pending_vo': self._safe_decimal(row.get('pending_vo') or row.get('pendingvo')),

                    # Invoicing
                    'gross_billed': self._safe_decimal(row.get('gross_billed') or row.get('grossbilled')),
                    'net_billed': self._safe_decimal(row.get('net_billed') or row.get('netbilled')),
                    'net_collected': self._safe_decimal(row.get('net_collected') or row.get('netcollected')),
                    'net_due': self._safe_decimal(row.get('net_due') or row.get('netdue')),

                    # Project Dates
                    'project_start_date': self._safe_date(row.get('project_start_date') or row.get('projectstartdate')),
                    'contract_finish_date': self._safe_date(row.get('contract_finish_date') or row.get('contractfinishdate')),
                    'forecast_finish_date': self._safe_date(row.get('forecast_finish_date') or row.get('forecastfinishdate')),
                    'delay_days': self._safe_int(row.get('delay_days') or row.get('delaydays')),

                    # Safety Metrics
                    'fatalities': self._safe_int(row.get('fatalities')),
                    'significant': self._safe_int(row.get('significant')),
                    'major': self._safe_int(row.get('major')),
                    'minor': self._safe_int(row.get('minor')),
                    'near_miss': self._safe_int(row.get('near_miss') or row.get('nearmiss')),
                    'total_manhours': self._safe_int(row.get('total_manhours') or row.get('totalmanhours')),
                    'loss_of_manhours': self._safe_int(row.get('loss_of_manhours') or row.get('lossofmanhours')),
                }
            )
            
            if not created:
                # Update existing data
                dashboard_data.planned_value = self._safe_decimal(row.get('planned_value') or row.get('plannedvalue'), dashboard_data.planned_value)
                dashboard_data.earned_value = self._safe_decimal(row.get('earned_value') or row.get('earnedvalue'), dashboard_data.earned_value)
                dashboard_data.bcwp = self._safe_decimal(row.get('bcwp'), dashboard_data.bcwp)
                dashboard_data.ac = self._safe_decimal(row.get('ac') or row.get('actual_cost'), dashboard_data.ac)
                dashboard_data.actual_billed = self._safe_decimal(row.get('actual_billed') or row.get('actualbilled'), dashboard_data.actual_billed)
                dashboard_data.original_contract_value = self._safe_decimal(row.get('original_contract_value') or row.get('originalcontractvalue'), dashboard_data.original_contract_value)
                dashboard_data.approved_vo = self._safe_decimal(row.get('approved_vo') or row.get('approvedvo'), dashboard_data.approved_vo)
                dashboard_data.revised_contract_value = self._safe_decimal(row.get('revised_contract_value') or row.get('revisedcontractvalue'), dashboard_data.revised_contract_value)
                dashboard_data.pending_vo = self._safe_decimal(row.get('pending_vo') or row.get('pendingvo'), dashboard_data.pending_vo)
                dashboard_data.gross_billed = self._safe_decimal(row.get('gross_billed') or row.get('grossbilled'), dashboard_data.gross_billed)
                dashboard_data.net_billed = self._safe_decimal(row.get('net_billed') or row.get('netbilled'), dashboard_data.net_billed)
                dashboard_data.net_collected = self._safe_decimal(row.get('net_collected') or row.get('netcollected'), dashboard_data.net_collected)
                dashboard_data.net_due = self._safe_decimal(row.get('net_due') or row.get('netdue'), dashboard_data.net_due)
                dashboard_data.project_start_date = self._safe_date(row.get('project_start_date') or row.get('projectstartdate'), dashboard_data.project_start_date)
                dashboard_data.contract_finish_date = self._safe_date(row.get('contract_finish_date') or row.get('contractfinishdate'), dashboard_data.contract_finish_date)
                dashboard_data.forecast_finish_date = self._safe_date(row.get('forecast_finish_date') or row.get('forecastfinishdate'), dashboard_data.forecast_finish_date)
                dashboard_data.delay_days = self._safe_int(row.get('delay_days') or row.get('delaydays'), dashboard_data.delay_days)
                dashboard_data.fatalities = self._safe_int(row.get('fatalities'), dashboard_data.fatalities)
                dashboard_data.significant = self._safe_int(row.get('significant'), dashboard_data.significant)
                dashboard_data.major = self._safe_int(row.get('major'), dashboard_data.major)
                dashboard_data.minor = self._safe_int(row.get('minor'), dashboard_data.minor)
                dashboard_data.near_miss = self._safe_int(row.get('near_miss') or row.get('nearmiss'), dashboard_data.near_miss)
                dashboard_data.total_manhours = self._safe_int(row.get('total_manhours') or row.get('totalmanhours'), dashboard_data.total_manhours)
                dashboard_data.loss_of_manhours = self._safe_int(row.get('loss_of_manhours') or row.get('lossofmanhours'), dashboard_data.loss_of_manhours)
                dashboard_data.save()

            serializer = ProjectDashboardDataSerializer(dashboard_data)
            return Response({
                'success': True,
                'message': 'Dashboard data imported successfully',
                'data': serializer.data
            })

        except (ValueError, TypeError) as e:
            return Response({
                'error': f'Invalid data format: {str(e)}',
                'details': str(e)
            }, status=400)
        except Exception as e:
            return Response({
                'error': f'Error importing data: {str(e)}',
                'details': str(e)
            }, status=500)

    @action(detail=True, methods=['get'], url_path='dashboard-data')
    def get_dashboard_data(self, request, pk=None):
        """
        Get dashboard data for a project.
        API: GET /api/projects-data/projects/{id}/dashboard-data/
        """
        project = self.get_object()
        try:
            dashboard_data = project.dashboard_data
        except ProjectDashboardData.DoesNotExist:
            # Fallback: Create dashboard data with project's initialized fields
            dashboard_data = ProjectDashboardData.objects.create(
                project=project,
                original_contract_value=project.original_contract_value,
                approved_vo=project.approved_vo,
                revised_contract_value=project.revised_contract_value,
                pending_vo=project.pending_vo,
                project_start_date=project.project_start,
                contract_finish_date=project.contract_finish,
                forecast_finish_date=project.forecast_finish,
                delay_days=project.delay_days
            )
            
        serializer = ProjectDashboardDataSerializer(dashboard_data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete_project(self, request, pk=None):
        """
        Mark a project as completed (HO / CEO / PMC Head / superuser).

        POST /api/projects/{id}/complete/
        Body: {
            "billing_status": "Pending" | "Completed",  # required
            "completion_notes": "Optional remarks",
            "billing_completion_notes": "Optional when billing_status=Completed"
        }
        """
        from accounts.rbac import can_manage_users
        from projects.services.project_completion import (
            ProjectCompletionBlocked,
            complete_project,
        )

        if not can_manage_users(request.user):
            return Response(
                {
                    "success": False,
                    "message": (
                        "Only Admin, Head Office, CEO, or PMC Head may mark "
                        "a project as completed."
                    ),
                },
                status=403,
            )

        project = self.get_object()
        notes = ""
        billing_status = None
        billing_notes = None
        if isinstance(request.data, dict):
            notes = request.data.get("completion_notes") or ""
            billing_status = request.data.get("billing_status")
            if "billing_completion_notes" in request.data:
                billing_notes = request.data.get("billing_completion_notes") or ""

        try:
            result = complete_project(
                project=project,
                actor=request.user,
                completion_notes=notes,
                billing_status=billing_status,
                billing_completion_notes=billing_notes,
            )
            return Response(result, status=200)
        except ProjectCompletionBlocked as exc:
            return Response(
                {
                    "success": False,
                    "message": exc.message,
                    "errors": exc.errors,
                },
                status=400,
            )

    @action(detail=True, methods=["post"], url_path="complete-billing")
    def complete_billing(self, request, pk=None):
        """
        Mark billing as completed for an already-completed project.

        POST /api/projects/{id}/complete-billing/
        Body: { "billing_completion_notes": "Optional remarks" }
        """
        from accounts.rbac import can_manage_users
        from projects.services.project_completion import (
            BillingCompletionBlocked,
            complete_billing,
        )

        if not can_manage_users(request.user):
            return Response(
                {
                    "success": False,
                    "message": (
                        "Only Admin, Head Office, CEO, or PMC Head may mark "
                        "billing as completed."
                    ),
                },
                status=403,
            )

        project = self.get_object()
        notes = ""
        if isinstance(request.data, dict):
            notes = request.data.get("billing_completion_notes") or ""

        try:
            result = complete_billing(
                project=project,
                actor=request.user,
                billing_completion_notes=notes,
            )
            return Response(result, status=200)
        except BillingCompletionBlocked as exc:
            return Response(
                {
                    "success": False,
                    "message": exc.message,
                    "errors": exc.errors,
                },
                status=400,
            )

    @action(detail=True, methods=['patch', 'put'], url_path='update-dashboard-data')
    def update_dashboard_data(self, request, pk=None):
        """
        Update dashboard data for a project (partial update).
        API: PATCH /api/projects-data/projects/{id}/update-dashboard-data/

        Accepts project_start_date, contract_finish_date, forecast_finish_date
        and syncs them back to the Project model so both sources stay consistent.
        """
        import logging
        logger = logging.getLogger(__name__)

        project = self.get_object()
        user = request.user

        # Check permissions
        if not (user.groups.filter(name__in=['Team Leader', 'Team Lead']).exists() or
                is_admin_user(user) or
                user.is_superuser or
                project.team_lead == user or
                project.pmc_head == user):
            return Response({'error': 'You do not have permission to update dashboard data'}, status=403)

        logger.debug(f"[update_dashboard_data] project={project.id} incoming payload={request.data}")

        try:
            dashboard_data = project.dashboard_data
        except ProjectDashboardData.DoesNotExist:
            dashboard_data = ProjectDashboardData(project=project)

        serializer = ProjectDashboardDataSerializer(
            dashboard_data,
            data=request.data,
            partial=True,
        )

        if not serializer.is_valid():
            logger.warning(f"[update_dashboard_data] validation errors={serializer.errors}")
            return Response({'success': False, 'errors': serializer.errors}, status=400)

        instance = serializer.save()
        logger.debug(f"[update_dashboard_data] saved dashboard_data id={instance.id} "
                     f"project_start_date={instance.project_start_date} "
                     f"contract_finish_date={instance.contract_finish_date} "
                     f"forecast_finish_date={instance.forecast_finish_date}")

        # ---------------------------------------------------------------
        # Sync date fields back to the Project model so that
        # GET /api/projects-data/projects/{id}/ always returns the latest
        # values regardless of which source the frontend reads from.
        # ---------------------------------------------------------------
        project_fields_changed = False

        if instance.project_start_date is not None:
            project.project_start = instance.project_start_date
            project_fields_changed = True

        if instance.contract_finish_date is not None:
            project.contract_finish = instance.contract_finish_date
            project_fields_changed = True

        if instance.forecast_finish_date is not None:
            project.forecast_finish = instance.forecast_finish_date
            project_fields_changed = True

        if project_fields_changed:
            project.save(update_fields=[
                'project_start',
                'contract_finish',
                'forecast_finish',
                'delay_days',
                'revised_contract_value',
                'updated_at',
            ])
            logger.debug(f"[update_dashboard_data] synced Project model: "
                         f"project_start={project.project_start} "
                         f"contract_finish={project.contract_finish} "
                         f"forecast_finish={project.forecast_finish}")

        # Re-fetch project with dashboard_data to build a complete response.
        # Returning both the dashboard_data fields AND the full project fields
        # (including project_start / contract_finish / forecast_finish) means
        # the frontend can update ALL of its state from this single response
        # without needing a separate re-fetch that could race or return stale data.
        project_refreshed = Project.objects.select_related(
            'dashboard_data', 'pmc_head', 'team_lead',
            'billing_site_engineer', 'qaqc_site_engineer', 'hse_site_engineer',
            'created_by',
        ).prefetch_related('sites', 'coordinators', 'site_engineers').get(pk=project.pk)

        from .serializers import ProjectSerializer as _ProjectSerializer
        project_data = _ProjectSerializer(project_refreshed, context={'request': request}).data

        return Response({
            'success': True,
            'message': 'Dashboard data updated successfully',
            # dashboard_data fields (what the frontend originally expected)
            'data': serializer.data,
            # full project snapshot — frontend should use this to update its state
            # so it never needs to re-fetch and risk getting stale cached data
            'project': project_data,
        })

    @action(detail=True, methods=['post'], url_path='assign-team-lead')
    def assign_team_lead(self, request, pk=None):
        """
        Assign a Team Leader to the project.
        API: POST /api/projects-data/projects/{id}/assign-team-lead/
        Body: { "user_id": <user_id> }
        """
        project = self.get_object()
        user = request.user

        # Check if user can assign team members
        if not self._check_assignment_permission(
            user,
            project,
            ['PMC Manager', 'Coordinator', 'PMC Head', 'CEO', 'Head Office', 'HO'],
            ['coordinators', 'pmc_head'],
        ) and not is_admin_user(user):
            return Response({'error': 'You do not have permission to assign a team lead'}, status=403)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)

        try:
            team_lead = self._get_user_by_id_safe(user_id)
            self._validate_user_role(team_lead, ['Team Leader'], 'Selected user must have Team Leader role')

            project.team_lead = team_lead
            project.save()

            from core.business_audit import write_business_audit
            from core.models import BusinessAuditLog

            write_business_audit(
                entity_type=BusinessAuditLog.ENTITY_ASSIGNMENT,
                action=BusinessAuditLog.ACTION_ASSIGNED,
                actor=request.user,
                entity_id=project.pk,
                project=project,
                detail=f"Team Leader {team_lead.username} assigned",
            )

            serializer = ProjectSerializer(project, context={'request': request})
            return Response({
                'success': True,
                'message': f'Team Leader {team_lead.username} assigned successfully',
                'project': serializer.data
            })
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.exception("assign_team_lead failed project_id=%s", project.pk)
            return Response(
                {'error': 'Failed to assign team lead. Please verify the user and try again.'},
                status=400,
            )

    @action(detail=True, methods=['post'], url_path='add-site-engineers')
    def add_site_engineers(self, request, pk=None):
        """
        Add Site Engineers to the project.
        API: POST /api/projects-data/projects/{id}/add-site-engineers/
        Body: { "user_ids": [<user_id1>, <user_id2>, ...] }
        """
        project = self.get_object()
        user = request.user
        
        # Check if user is a Team Lead for this project or PMC Head
        if not (user.groups.filter(name__in=['Team Leader']).exists() or 
                is_admin_user(user) or
                user.is_superuser or
                project.team_lead == user or
                project.pmc_head == user):
            return Response({'error': 'You do not have permission to add site engineers'}, status=403)
        
        user_ids = request.data.get('user_ids', [])
        if not user_ids:
            return Response({'error': 'user_ids array is required'}, status=400)
        
        # Limit to 3 site engineers
        current_count = project.site_engineers.count()
        if current_count + len(user_ids) > 3:
            return Response({'error': f'Cannot add more than 3 site engineers. Currently have {current_count}, can add {3 - current_count} more.'}, status=400)
        
        added_engineers = []
        errors = []
        
        for user_id in user_ids:
            try:
                site_engineer = User.objects.get(id=user_id)
                # Verify user has Site Engineer group
                if not site_engineer.groups.filter(name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']).exists():
                    errors.append(f'User {user_id} must have Site Engineer role')
                    continue
                
                project.site_engineers.add(site_engineer)
                added_engineers.append(site_engineer.username)
            except User.DoesNotExist:
                errors.append(f'User {user_id} not found')
        
        project.save()
        serializer = ProjectSerializer(project, context={'request': request})
        
        return Response({
            'success': True,
            'message': f'Site Engineers added successfully: {added_engineers}',
            'warnings': errors if errors else None,
            'project': serializer.data
        })

    @action(detail=True, methods=['post'], url_path='add-billing-site-engineer')
    def add_billing_site_engineer(self, request, pk=None):
        """
        Add a Billing Site Engineer to the project.
        API: POST /api/projects-data/projects/{id}/add-billing-site-engineer/
        Body: { "user_id": <user_id> }
        """
        project = self.get_object()
        user = request.user
        
        # Check if user is a Team Lead for this project or PMC Head
        if not (user.groups.filter(name__in=['Team Leader']).exists() or 
                is_admin_user(user) or
                user.is_superuser or
                project.team_lead == user or
                project.pmc_head == user):
            return Response({'error': 'You do not have permission to add a billing site engineer'}, status=403)
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)
        
        try:
            billing_engineer = User.objects.get(id=user_id)
            # Verify user has Billing Site Engineer group
            if not billing_engineer.groups.filter(name='Billing Site Engineer').exists():
                return Response({'error': 'Selected user must have Billing Site Engineer role'}, status=400)
            
            # Check if already assigned as billing engineer
            if project.billing_site_engineer == billing_engineer:
                return Response({'error': 'This user is already assigned as Billing Site Engineer'}, status=400)
            
            project.billing_site_engineer = billing_engineer
            project.save()
            serializer = ProjectSerializer(project, context={'request': request})
            
            return Response({
                'success': True,
                'message': f'Billing Site Engineer {billing_engineer.username} added successfully',
                'project': serializer.data
            })
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

    @action(detail=True, methods=['post'], url_path='add-qaqc-site-engineer')
    def add_qaqc_site_engineer(self, request, pk=None):
        """
        Add a QAQC Site Engineer to the project.
        API: POST /api/projects-data/projects/{id}/add-qaqc-site-engineer/
        Body: { "user_id": <user_id> }
        """
        project = self.get_object()
        user = request.user
        
        # Check if user is a Team Lead for this project or PMC Head
        if not (user.groups.filter(name__in=['Team Leader']).exists() or 
                is_admin_user(user) or
                user.is_superuser or
                project.team_lead == user or
                project.pmc_head == user):
            return Response({'error': 'You do not have permission to add a QAQC site engineer'}, status=403)
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)
        
        try:
            qaqc_engineer = User.objects.get(id=user_id)
            # Verify user has QAQC Site Engineer group
            if not qaqc_engineer.groups.filter(name='QAQC Site Engineer').exists():
                return Response({'error': 'Selected user must have QAQC Site Engineer role'}, status=400)
            
            # Check if already assigned as QAQC engineer
            if project.qaqc_site_engineer == qaqc_engineer:
                return Response({'error': 'This user is already assigned as QAQC Site Engineer'}, status=400)
            
            project.qaqc_site_engineer = qaqc_engineer
            project.save()
            serializer = ProjectSerializer(project, context={'request': request})
            
            return Response({
                'success': True,
                'message': f'QAQC Site Engineer {qaqc_engineer.username} added successfully',
                'project': serializer.data
            })
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

    @action(detail=True, methods=['post'], url_path='add-hse-site-engineer')
    def add_hse_site_engineer(self, request, pk=None):
        """
        Add an HSE Site Engineer to the project.
        API: POST /api/projects/{id}/add-hse-site-engineer/
        Body: { "user_id": <user_id> }
        """
        project = self.get_object()
        user = request.user

        if not (user.groups.filter(name__in=['Team Leader']).exists() or
                is_admin_user(user) or
                user.is_superuser or
                project.team_lead == user or
                project.pmc_head == user):
            return Response({'error': 'You do not have permission to add an HSE site engineer'}, status=403)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)

        try:
            hse_engineer = User.objects.get(id=user_id)
            if not hse_engineer.groups.filter(name='HSE Site Engineer').exists():
                return Response({'error': 'Selected user must have HSE Site Engineer role'}, status=400)

            if project.hse_site_engineer == hse_engineer:
                return Response({'error': 'This user is already assigned as HSE Site Engineer'}, status=400)

            project.hse_site_engineer = hse_engineer
            project.save()
            serializer = ProjectSerializer(project, context={'request': request})

            return Response({
                'success': True,
                'message': f'HSE Site Engineer {hse_engineer.username} added successfully',
                'project': serializer.data
            })
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

    @action(detail=True, methods=['post'], url_path='assign-coordinator')
    def assign_coordinator(self, request, pk=None):
        """
        Assign a PMC Manager to the project.
        API: POST /api/projects-data/projects/{id}/assign-coordinator/
        Body: { "user_id": <user_id> }

        URL path kept as assign-coordinator for frontend compatibility.
        """
        project = self.get_object()
        user = request.user
        
        # Check if user is PMC Head or CEO
        if not (is_admin_user(user) or user.is_superuser or project.pmc_head == user):
            return Response({'error': 'You do not have permission to assign a PMC Manager'}, status=403)
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)
        
        try:
            coordinator = User.objects.get(id=user_id)
            # Verify user has PMC Manager (or legacy Coordinator) group
            if not coordinator.groups.filter(name__in=['PMC Manager', 'Coordinator']).exists():
                return Response({'error': 'Selected user must have PMC Manager role'}, status=400)
            
            project.coordinators.add(coordinator)
            project.save()
            
            serializer = ProjectSerializer(project, context={'request': request})
            return Response({
                'success': True,
                'message': f'PMC Manager {coordinator.username} assigned successfully',
                'project': serializer.data
            })
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

    @action(detail=False, methods=['get'], url_path='available-users')
    def available_users(self, request):
        """
        Get available users that can be assigned to projects.
        Filters out users who are already assigned to active/in-progress projects.
        API: GET /api/projects-data/projects/available-users/?role=Team%20Leader
        """
        role = request.query_params.get('role')
        group_name = role if role else 'Team Leader'
        # Legacy alias: Coordinator → PMC Manager
        if group_name == 'Coordinator':
            group_name = 'PMC Manager'

        # Get all users with the specified role
        users = User.objects.filter(groups__name=group_name).distinct()
        if group_name == 'PMC Manager':
            # Include any users still on the legacy Coordinator group during migration
            users = User.objects.filter(
                groups__name__in=['PMC Manager', 'Coordinator']
            ).distinct()
        
        # Get IDs of users who are already assigned to active projects
        # An active project is any project NOT in 'completed' or 'cancelled' status
        excluded_user_ids = set()
        
        if group_name == 'Team Leader':
            # Exclude Team Leaders who are already assigned to active projects
            active_tl_projects = Project.objects.exclude(
                status__in=['completed', 'cancelled', 'not_started']
            ).exclude(team_lead__isnull=True)
            excluded_user_ids.update(
                active_tl_projects.values_list('team_lead_id', flat=True)
            )
        elif group_name in [
            'Site Engineer',
            'Billing Site Engineer',
            'QAQC Site Engineer',
            'HSE Site Engineer',
        ]:
            # Exclude Site Engineers who are already assigned to active projects
            # Check all site engineer fields
            active_se_projects = Project.objects.exclude(
                status__in=['completed', 'cancelled', 'not_started']
            )
            
            # Site Engineers in ManyToMany field
            excluded_user_ids.update(
                active_se_projects.values_list('site_engineers__id', flat=True)
            )
            # Billing Site Engineer
            excluded_user_ids.update(
                active_se_projects.exclude(
                    billing_site_engineer__isnull=True
                ).values_list('billing_site_engineer_id', flat=True)
            )
            # QAQC Site Engineer
            excluded_user_ids.update(
                active_se_projects.exclude(
                    qaqc_site_engineer__isnull=True
                ).values_list('qaqc_site_engineer_id', flat=True)
            )
            # HSE Site Engineer
            excluded_user_ids.update(
                active_se_projects.exclude(
                    hse_site_engineer__isnull=True
                ).values_list('hse_site_engineer_id', flat=True)
            )
        
        # Filter out users who are already assigned to active projects
        available_users = users.exclude(id__in=excluded_user_ids)
        
        user_list = []
        for u in available_users:
            user_list.append({
                'id': u.id,
                'username': u.username,
                'name': f"{u.first_name} {u.last_name}".strip() or u.username,
                'email': u.email,
                'role': group_name
            })
        
        return Response(user_list)

    # ==========================================================================
    # Project Initialization API
    # ==========================================================================
    @action(detail=False, methods=['post'], url_path='init')
    def init_project(self, request):
        """
        Initialize a new project with PMC Head input.

        API: POST /api/projects/init/

        Input fields:
        - name (required)
        - location (optional)
        - project_start (optional)
        - contract_finish (optional)
        - forecast_finish (optional)
        - original_contract_value (optional, >= 0)
        - approved_vo (optional, >= 0)
        - pending_vo (optional, >= 0)
        - bac (optional, >= 0)
        - working_hours_per_day (optional, >= 0)
        - working_days_per_month (optional, >= 1)
        - assigned_users (optional, list of user IDs)

        Auto-calculated fields (returned in response):
        - revised_contract_value = original_contract_value + approved_vo
        - delay_days = (forecast_finish - contract_finish).days
        """
        serializer = ProjectInitSerializer(data=request.data)
        
        if serializer.is_valid():
            # Get the current user as creator
            user = request.user if request.user.is_authenticated else None
            
            # Create the project
            project = serializer.save()
            
            # Set created_by and pmc_head if user is authenticated
            if user:
                project.created_by = user
                if is_admin_user(user):
                    project.pmc_head = user
                project.save()
            
            # Return the created project with calculated fields
            response_serializer = ProjectInitSerializer(project)
            return Response({
                'success': True,
                'message': 'Project initialized successfully',
                'project': response_serializer.data
            }, status=201)
        
        return Response({
            'success': False,
            'message': 'Some information is missing or invalid. Please review the highlighted fields.',
            'errors': serializer.errors
        }, status=400)

    @action(detail=False, methods=['get'], url_path='init-list')
    def list_init_projects(self, request):
        """
        Get list of projects with initialization fields only.
        
        API: GET /api/projects/init-list/
        API: GET /api/projects-data/projects/init-list/
        
        Returns only the project initialization fields:
        - name, location
        - project_start, contract_finish, forecast_finish
        - original_contract_value, approved_vo, pending_vo
        - bac
        - working_hours_per_day, working_days_per_month
        - revised_contract_value, delay_days
        """
        queryset = self.get_queryset()
        serializer = ProjectInitSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["delete"],
        url_path=r"init-list/(?P<site_id>[^/.]+)",
        url_name="init-list-delete-site",
    )
    def delete_init_site(self, request, site_id=None):
        """
        Safely delete a Site by id (Init List delete action).

        DELETE /api/projects/init-list/{site_id}/
        DELETE /api/projects-data/projects/init-list/{site_id}/

        Allowed: Admin (superuser), Head Office, CEO, PMC Head.
        Blocked when reverse FK dependencies exist (tasks / ops DPRs).
        """
        from accounts.permissions import CanDeleteSites
        from accounts.rbac import can_manage_users
        from projects.services.site_deletion import (
            SiteDeleteBlocked,
            delete_site_safe,
        )

        # Explicit RBAC (ProjectViewSet default allows write when project unresolved).
        if not can_manage_users(request.user):
            return Response(
                {
                    "success": False,
                    "message": CanDeleteSites.message,
                },
                status=403,
            )

        try:
            site_pk = int(site_id)
        except (TypeError, ValueError):
            return Response(
                {"success": False, "message": "Site not found."},
                status=404,
            )

        site = (
            Site.objects.select_related("project")
            .filter(pk=site_pk)
            .only("id", "name", "project_id", "project__name")
            .first()
        )
        if site is None:
            return Response(
                {"success": False, "message": "Site not found."},
                status=404,
            )

        try:
            result = delete_site_safe(
                site=site, actor=request.user, request=request
            )
            return Response(result, status=200)
        except SiteDeleteBlocked as exc:
            return Response(
                {
                    "success": False,
                    "message": (
                        "This site cannot be deleted because it is referenced "
                        "by existing records."
                    ),
                    "errors": [
                        {
                            "field": "non_field_errors",
                            "message": (
                                "This site cannot be deleted because it is "
                                "referenced by existing records."
                            ),
                        }
                    ],
                    "dependencies": exc.dependencies,
                },
                status=400,
            )


class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer

    def get_queryset(self):
        # Never expose sites for merged / completed / on-hold projects.
        # Completed projects still keep sites historically — allow list when
        # project_id is explicit; default hide sites of completed/on_hold/merged
        # was prior behaviour for live dropdowns.
        qs = Site.objects.select_related("project").exclude(
            project__status__in=["merged", "on_hold"]
        ).order_by("-created_at", "name")
        # Keep completed project sites visible for historical views.
        project_id = self.request.query_params.get("project_id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        else:
            qs = qs.exclude(project__status="completed")
        # Optional site status filter; default keeps active + not_started for live projects.
        site_status = (self.request.query_params.get("status") or "").strip()
        if site_status:
            qs = qs.filter(status=site_status)
        return qs

    def perform_create(self, serializer):
        from accounts.rbac_checks import assert_project_writable

        project = serializer.validated_data.get("project")
        assert_project_writable(project)
        serializer.save()

    def perform_update(self, serializer):
        from accounts.rbac_checks import assert_project_writable

        assert_project_writable(serializer.instance.project)
        serializer.save()

    def perform_destroy(self, instance):
        from accounts.rbac_checks import assert_project_writable

        assert_project_writable(instance.project)
        instance.delete()


class ProjectLogViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Project Logs (Issues & Concerns + Risks & Actions).
    
    Endpoints:
    - GET    /api/project-logs/<project_id>/     → Get logs for a project (creates if not exists)
    - PATCH  /api/project-logs/<project_id>/     → Update logs (replaces entries)
    - PUT    /api/project-logs/<project_id>/     → Full update
    """
    serializer_class = ProjectLogSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'project_id'

    def get_queryset(self):
        project_id = self.kwargs.get('project_id')
        if project_id:
            return ProjectLog.objects.filter(project_id=project_id).prefetch_related('entries')
        return ProjectLog.objects.none()

    def get_object(self):
        """
        Get or create ProjectLog for the given project.
        """
        project_id = self.kwargs.get('project_id')
        
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Project not found")

        project_log, created = ProjectLog.objects.get_or_create(
            project=project,
            defaults={
                'created_by': self.request.user if self.request.user.is_authenticated else None
            }
        )
        
        if created:
            project_log.updated_by = self.request.user
            project_log.save()
            
        return project_log

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
