from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from .models import Project, Site
from .serializers import ProjectSerializer, SiteSerializer
import pandas as pd
from datetime import datetime
from django.utils.dateparse import parse_date
from .models import Project, Site, ProjectDashboardData
from .serializers import ProjectSerializer, SiteSerializer, ProjectDashboardDataSerializer

class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Swagger / OpenAPI schema generation runs without a real user
        if getattr(self, "swagger_fake_view", False):
            return Project.objects.none()
        # Return all projects for PMC Head, or filter by assignment for others
        user = self.request.user
        if user.groups.filter(name='PMC Head').exists() or user.is_superuser:
            return Project.objects.all().order_by('-created_at')
        
        # For Site Engineers, show active/planning projects they are assigned to OR all active projects
        if user.groups.filter(name='Site Engineer').exists():
            # First, get projects explicitly assigned to this site engineer
            assigned_projects = Project.objects.filter(
                Q(team_lead=user) |
                Q(site_engineers=user) |
                Q(coordinators=user) |
                Q(pmc_head=user)
            ).distinct()
            
            # If no assigned projects, show active/planning projects so they can submit DPRs
            if not assigned_projects.exists():
                return Project.objects.filter(
                    status__in=['active', 'planning']
                ).order_by('-created_at')
            
            return assigned_projects.order_by('-created_at')
        
        # For other roles (Team Lead, Coordinator), show projects they are assigned to
        return Project.objects.filter(
            Q(team_lead=user) |
            Q(site_engineers=user) |
            Q(coordinators=user) |
            Q(pmc_head=user)
        ).distinct().order_by('-created_at')

    def perform_create(self, serializer):
        """Set creator and auto-assign pmc_head if applicable."""
        user = self.request.user
        save_kwargs = {'created_by': user}
        if user.groups.filter(name='PMC Head').exists() or user.is_superuser:
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
                documents.append({
                    'id': project.id,
                    'project_id': project.id,
                    'project_name': project.name,
                    'file_name': project.documentation_file.name.split('/')[-1],
                    'file_url': request.build_absolute_uri(project.documentation_file.url),
                    'file_type': project.documentation_file.name.split('.')[-1].upper(),
                    'uploaded_at': project.updated_at.isoformat() if project.updated_at else None,
                    'uploaded_by': project.pmc_head.username if project.pmc_head else None,
                })
        
        return Response(documents)

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
            
            # Helper function to safely convert values
            def safe_decimal(value, default=None):
                if pd.isna(value) or value == '':
                    return default
                try:
                    return float(value)
                except:
                    return default
            
            def safe_int(value, default=0):
                if pd.isna(value) or value == '':
                    return default
                try:
                    return int(float(value))
                except:
                    return default
            
            def safe_date(value, default=None):
                if pd.isna(value) or value == '':
                    return default
                if isinstance(value, str):
                    try:
                        return parse_date(value)
                    except:
                        return default
                if isinstance(value, datetime):
                    return value.date()
                return default
            
            # Map Excel columns to model fields
            dashboard_data, created = ProjectDashboardData.objects.get_or_create(
                project=project,
                defaults={
                    # Financial Metrics
                    'planned_value': safe_decimal(row.get('planned_value') or row.get('plannedvalue')),
                    'earned_value': safe_decimal(row.get('earned_value') or row.get('earnedvalue')),
                    'bcwp': safe_decimal(row.get('bcwp')),
                    'ac': safe_decimal(row.get('ac') or row.get('actual_cost')),
                    'actual_billed': safe_decimal(row.get('actual_billed') or row.get('actualbilled')),
                    
                    # Contract Values
                    'original_contract_value': safe_decimal(row.get('original_contract_value') or row.get('originalcontractvalue')),
                    'approved_vo': safe_decimal(row.get('approved_vo') or row.get('approvedvo')),
                    'revised_contract_value': safe_decimal(row.get('revised_contract_value') or row.get('revisedcontractvalue')),
                    'pending_vo': safe_decimal(row.get('pending_vo') or row.get('pendingvo')),
                    
                    # Invoicing
                    'gross_billed': safe_decimal(row.get('gross_billed') or row.get('grossbilled')),
                    'net_billed': safe_decimal(row.get('net_billed') or row.get('netbilled')),
                    'net_collected': safe_decimal(row.get('net_collected') or row.get('netcollected')),
                    'net_due': safe_decimal(row.get('net_due') or row.get('netdue')),
                    
                    # Project Dates
                    'project_start_date': safe_date(row.get('project_start_date') or row.get('projectstartdate')),
                    'contract_finish_date': safe_date(row.get('contract_finish_date') or row.get('contractfinishdate')),
                    'forecast_finish_date': safe_date(row.get('forecast_finish_date') or row.get('forecastfinishdate')),
                    'delay_days': safe_int(row.get('delay_days') or row.get('delaydays')),
                    
                    # Safety Metrics
                    'fatalities': safe_int(row.get('fatalities')),
                    'significant': safe_int(row.get('significant')),
                    'major': safe_int(row.get('major')),
                    'minor': safe_int(row.get('minor')),
                    'near_miss': safe_int(row.get('near_miss') or row.get('nearmiss')),
                    'total_manhours': safe_int(row.get('total_manhours') or row.get('totalmanhours')),
                    'loss_of_manhours': safe_int(row.get('loss_of_manhours') or row.get('lossofmanhours')),
                }
            )
            
            if not created:
                # Update existing data
                dashboard_data.planned_value = safe_decimal(row.get('planned_value') or row.get('plannedvalue'), dashboard_data.planned_value)
                dashboard_data.earned_value = safe_decimal(row.get('earned_value') or row.get('earnedvalue'), dashboard_data.earned_value)
                dashboard_data.bcwp = safe_decimal(row.get('bcwp'), dashboard_data.bcwp)
                dashboard_data.ac = safe_decimal(row.get('ac') or row.get('actual_cost'), dashboard_data.ac)
                dashboard_data.actual_billed = safe_decimal(row.get('actual_billed') or row.get('actualbilled'), dashboard_data.actual_billed)
                dashboard_data.original_contract_value = safe_decimal(row.get('original_contract_value') or row.get('originalcontractvalue'), dashboard_data.original_contract_value)
                dashboard_data.approved_vo = safe_decimal(row.get('approved_vo') or row.get('approvedvo'), dashboard_data.approved_vo)
                dashboard_data.revised_contract_value = safe_decimal(row.get('revised_contract_value') or row.get('revisedcontractvalue'), dashboard_data.revised_contract_value)
                dashboard_data.pending_vo = safe_decimal(row.get('pending_vo') or row.get('pendingvo'), dashboard_data.pending_vo)
                dashboard_data.gross_billed = safe_decimal(row.get('gross_billed') or row.get('grossbilled'), dashboard_data.gross_billed)
                dashboard_data.net_billed = safe_decimal(row.get('net_billed') or row.get('netbilled'), dashboard_data.net_billed)
                dashboard_data.net_collected = safe_decimal(row.get('net_collected') or row.get('netcollected'), dashboard_data.net_collected)
                dashboard_data.net_due = safe_decimal(row.get('net_due') or row.get('netdue'), dashboard_data.net_due)
                dashboard_data.project_start_date = safe_date(row.get('project_start_date') or row.get('projectstartdate'), dashboard_data.project_start_date)
                dashboard_data.contract_finish_date = safe_date(row.get('contract_finish_date') or row.get('contractfinishdate'), dashboard_data.contract_finish_date)
                dashboard_data.forecast_finish_date = safe_date(row.get('forecast_finish_date') or row.get('forecastfinishdate'), dashboard_data.forecast_finish_date)
                dashboard_data.delay_days = safe_int(row.get('delay_days') or row.get('delaydays'), dashboard_data.delay_days)
                dashboard_data.fatalities = safe_int(row.get('fatalities'), dashboard_data.fatalities)
                dashboard_data.significant = safe_int(row.get('significant'), dashboard_data.significant)
                dashboard_data.major = safe_int(row.get('major'), dashboard_data.major)
                dashboard_data.minor = safe_int(row.get('minor'), dashboard_data.minor)
                dashboard_data.near_miss = safe_int(row.get('near_miss') or row.get('nearmiss'), dashboard_data.near_miss)
                dashboard_data.total_manhours = safe_int(row.get('total_manhours') or row.get('totalmanhours'), dashboard_data.total_manhours)
                dashboard_data.loss_of_manhours = safe_int(row.get('loss_of_manhours') or row.get('lossofmanhours'), dashboard_data.loss_of_manhours)
                dashboard_data.save()
            
            serializer = ProjectDashboardDataSerializer(dashboard_data)
            return Response({
                'success': True,
                'message': 'Dashboard data imported successfully',
                'data': serializer.data
            })
            
        except Exception as e:
            return Response({
                'error': f'Error importing data: {str(e)}',
                'details': str(e)
            }, status=400)

    @action(detail=True, methods=['get'], url_path='dashboard-data')
    def get_dashboard_data(self, request, pk=None):
        """
        Get dashboard data for a project.
        API: GET /api/projects-data/projects/{id}/dashboard-data/
        """
        project = self.get_object()
        try:
            dashboard_data = project.dashboard_data
            serializer = ProjectDashboardDataSerializer(dashboard_data)
            return Response(serializer.data)
        except ProjectDashboardData.DoesNotExist:
            return Response({'error': 'No dashboard data found for this project'}, status=404) 

class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filter sites based on the project ID if provided in the URL
        project_id = self.request.query_params.get('project_id')
        if project_id:
            return Site.objects.filter(project_id=project_id)
        return Site.objects.all()
