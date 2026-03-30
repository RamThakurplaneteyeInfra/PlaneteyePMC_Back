from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Task, DailyProgressReport
from .serializers import TaskSerializer, DailyProgressReportSerializer

class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = []

    def get_queryset(self):
        # Filter tasks by site if site_id is provided
        site_id = self.request.query_params.get('site_id')
        if site_id:
            return Task.objects.filter(site_id=site_id)
        
        # Role-based filtering for tasks
        user = self.request.user
        if user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser:
            return Task.objects.all()
        elif user.groups.filter(name='Team Leader').exists():
            # Team lead sees tasks from their assigned projects
            from projects.models import Project
            project_ids = Project.objects.filter(team_lead=user).values_list('id', flat=True)
            site_ids = Task.objects.filter(project_id__in=project_ids).values_list('site_id', flat=True)
            return Task.objects.filter(site_id__in=site_ids)
        elif user.groups.filter(name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']).exists():
            # Site engineer sees only their assigned tasks
            return Task.objects.filter(assigned_to=user)
        
        return Task.objects.all()


class DailyProgressReportViewSet(viewsets.ModelViewSet):
    queryset = DailyProgressReport.objects.all()
    serializer_class = DailyProgressReportSerializer
    permission_classes = []

    def get_queryset(self):
        """
        Role-based filtering for DPRs:
        - PMC Head / Admin: sees all DPRs
        - Team Lead: sees DPRs from projects they lead
        - Site Engineer: sees only their own submitted DPRs
        """
        user = self.request.user
        
        # Check user groups
        is_admin = user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser
        is_team_lead = user.groups.filter(name='Team Leader').exists()
        is_site_engineer = user.groups.filter(name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']).exists()
        
        # Filter by task_id if provided
        task_id = self.request.query_params.get('task_id')
        if task_id:
            return DailyProgressReport.objects.filter(task_id=task_id)
        
        # Admin sees all
        if is_admin:
            return DailyProgressReport.objects.all().order_by('-created_at')
        
        # Team Lead sees DPRs from their projects
        if is_team_lead:
            from projects.models import Project
            project_ids = Project.objects.filter(team_lead=user).values_list('id', flat=True)
            return DailyProgressReport.objects.filter(project_id__in=project_ids).order_by('-created_at')
        
        # Site Engineer sees only their own DPRs
        if is_site_engineer:
            return DailyProgressReport.objects.filter(submitted_by=user).order_by('-created_at')
        
        # Default: return all (for backward compatibility)
        return DailyProgressReport.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        """Automatically set the submitted_by user to the current user."""
        data = self.request.data
        project_id = data.get('project')
        site_id = data.get('site')
        
        save_kwargs = {'submitted_by': self.request.user}
        
        if project_id:
            try:
                save_kwargs['project_id'] = int(project_id)
            except (ValueError, TypeError):
                pass
        
        if site_id:
            try:
                save_kwargs['site_id'] = int(site_id)
            except (ValueError, TypeError):
                pass
                
        serializer.save(**save_kwargs)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """
        Approve a DPR.
        API: POST /api/operations/reports/{id}/approve/
        """
        dpr = self.get_object()
        
        # Check if user has permission to approve
        user = request.user
        is_admin = user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser
        is_team_lead = user.groups.filter(name='Team Leader').exists()
        
        if not (is_admin or is_team_lead):
            return Response(
                {'error': 'Only Team Leader or PMC Head can approve DPRs'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if already approved
        if dpr.status == 'APPROVED':
            return Response(
                {'error': 'DPR is already approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Approve the DPR
        dpr.status = 'APPROVED'
        dpr.approved_by = user
        dpr.reviewed_at = timezone.now()
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response({
            'message': 'DPR approved successfully',
            'dpr': serializer.data
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """
        Reject a DPR with a reason.
        API: POST /api/operations/reports/{id}/reject/
        Body: {"reason": "rejection reason text"}
        """
        dpr = self.get_object()
        
        # Check if user has permission to reject
        user = request.user
        is_admin = user.groups.filter(name__in=['PMC Head', 'CEO']).exists() or user.is_superuser
        is_team_lead = user.groups.filter(name='Team Leader').exists()
        
        if not (is_admin or is_team_lead):
            return Response(
                {'error': 'Only Team Leader or PMC Head can reject DPRs'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get rejection reason from request
        rejection_reason = request.data.get('reason', '')
        if not rejection_reason:
            return Response(
                {'error': 'Rejection reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Reject the DPR
        dpr.status = 'REJECTED'
        dpr.rejection_reason = rejection_reason
        dpr.approved_by = user
        dpr.reviewed_at = timezone.now()
        dpr.save()
        
        serializer = self.get_serializer(dpr)
        return Response({
            'message': 'DPR rejected successfully',
            'dpr': serializer.data
        })

    @action(detail=False, methods=['get'])
    def submitted_documents(self, request):
        """
        Get submitted documents (DPRs) for portfolio view.
        API: GET /api/operations/reports/submitted_documents/
        Query params:
        - status: filter by status (PENDING, APPROVED, REJECTED)
        - project_id: filter by project
        """
        queryset = self.get_queryset()
        
        # Additional filters
        status_filter = request.query_params.get('status')
        project_id = request.query_params.get('project_id')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Get recent submissions (last 20)
        queryset = queryset[:20]
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
