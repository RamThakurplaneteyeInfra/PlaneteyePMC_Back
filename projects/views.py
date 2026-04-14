from datetime import datetime
from typing import List, Dict, Any

import pandas as pd
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Project, ProjectDashboardData, Site
from .serializers import (
    ProjectDashboardDataSerializer,
    ProjectInitSerializer,
    ProjectSerializer,
    SiteSerializer,
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
    permission_classes = []

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
            'billing_site_engineer',
            'qaqc_site_engineer',
            'created_by'
        ).prefetch_related(
            'sites',
            'coordinators',
            'site_engineers'
        )

        # Return all projects for unauthenticated users
        user = self.request.user
        if not user.is_authenticated:
            return base_queryset.order_by('-created_at')

        # Return all projects for PMC Head and Coordinator, or filter by assignment for others
        if user.groups.filter(name__in=['PMC Head', 'CEO', 'Coordinator']).exists() or user.is_superuser:
            return base_queryset.order_by('-created_at')

        # For Site Engineers, show active/planning projects they are assigned to OR all active projects
        if user.groups.filter(name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']).exists():
            # First, get projects explicitly assigned to this site engineer
            assigned_projects = base_queryset.filter(
                Q(team_lead=user) |
                Q(site_engineers=user) |
                Q(billing_site_engineer=user) |
                Q(qaqc_site_engineer=user) |
                Q(coordinators=user) |
                Q(pmc_head=user)
            ).distinct()

            # If no assigned projects, show active/planning projects so they can submit DPRs
            if not assigned_projects.exists():
                return base_queryset.filter(
                    status__in=['active', 'planning']
                ).order_by('-created_at')

            return assigned_projects.order_by('-created_at')

        # For other roles (Team Lead, Coordinator), show projects they are assigned to
        return base_queryset.filter(
            Q(team_lead=user) |
            Q(site_engineers=user) |
            Q(coordinators=user) |
            Q(pmc_head=user)
        ).distinct().order_by('-created_at')

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
        """Set creator and auto-assign pmc_head if applicable."""
        user = self.request.user
        save_kwargs = {'created_by': user}
        if user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser:
            save_kwargs['pmc_head'] = user
        serializer.save(**save_kwargs)

    @action(detail=False, methods=['get'])
    def documents(self, request):
        """
        Get project documents for the vault.
        API: GET /api/projects-data/projects/documents/
        Returns all projects that have documentation files uploaded.
        """
        queryset = self.get_queryset()

        # Filter to only projects with documentation
        docs_projects = queryset.filter(
            has_documentation=True,
            documentation_file__isnull=False
        ).exclude(documentation_file='')

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
        if not self._check_assignment_permission(user, project, ['Coordinator', 'PMC Head', 'CEO'], ['coordinators', 'pmc_head']):
            return Response({'error': 'You do not have permission to assign a team lead'}, status=403)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)

        try:
            team_lead = self._get_user_by_id_safe(user_id)
            self._validate_user_role(team_lead, ['Team Leader'], 'Selected user must have Team Leader role')

            project.team_lead = team_lead
            project.save()

            serializer = ProjectSerializer(project, context={'request': request})
            return Response({
                'success': True,
                'message': f'Team Leader {team_lead.username} assigned successfully',
                'project': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=400)

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
        if not (user.groups.filter(name__in=['Team Leader', 'PMC Head', 'CEO']).exists() or 
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
        if not (user.groups.filter(name__in=['Team Leader', 'PMC Head', 'CEO']).exists() or 
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
        if not (user.groups.filter(name__in=['Team Leader', 'PMC Head', 'CEO']).exists() or 
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

    @action(detail=True, methods=['post'], url_path='assign-coordinator')
    def assign_coordinator(self, request, pk=None):
        """
        Assign a Coordinator to the project.
        API: POST /api/projects-data/projects/{id}/assign-coordinator/
        Body: { "user_id": <user_id> }
        """
        project = self.get_object()
        user = request.user
        
        # Check if user is PMC Head or CEO
        if not (user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser or project.pmc_head == user):
            return Response({'error': 'You do not have permission to assign a coordinator'}, status=403)
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=400)
        
        try:
            coordinator = User.objects.get(id=user_id)
            # Verify user has Coordinator group
            if not coordinator.groups.filter(name='Coordinator').exists():
                return Response({'error': 'Selected user must have Coordinator role'}, status=400)
            
            project.coordinators.add(coordinator)
            project.save()
            
            serializer = ProjectSerializer(project, context={'request': request})
            return Response({
                'success': True,
                'message': f'Coordinator {coordinator.username} assigned successfully',
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
        
        # Get all users with the specified role
        users = User.objects.filter(groups__name=group_name).distinct()
        
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
        elif group_name in ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']:
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
        
        API: POST /api/projects-data/projects/init/
        
        Input fields:
        - name (required, unique)
        - location (required)
        - project_start (required)
        - contract_finish (required)
        - forecast_finish (optional)
        - original_contract_value (required, >= 0)
        - approved_vo (required, >= 0)
        - pending_vo (required, >= 0)
        - bac (required, > 0)
        - working_hours_per_day (required, > 0)
        - working_days_per_month (required, > 0)
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
                if user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser:
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
            'errors': serializer.errors
        }, status=400)

    @action(detail=False, methods=['get'], url_path='init-list')
    def list_init_projects(self, request):
        """
        Get list of projects with initialization fields only.
        
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


class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    permission_classes = []

    def get_queryset(self):
        # Filter sites based on the project ID if provided in the URL
        project_id = self.request.query_params.get('project_id')
        if project_id:
            return Site.objects.filter(project_id=project_id)
        return Site.objects.all()
