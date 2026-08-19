from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.utils import timezone
from .models import ScopeCategory, ScopeSubCategory, MonthlyScopeWork, ScopeAssignment
from .serializers import (
    ScopeCategorySerializer, ScopeSubCategorySerializer,
    MonthlyScopeWorkSerializer, ScopeAssignmentSerializer
)
from .permissions import IsTeamLeader, IsSiteEngineer, CanManageScope, CanViewAssignedScopes, CanViewScopes
from .services import ScopeProgressService


class ScopeCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Scope Categories
    """
    queryset = ScopeCategory.objects.filter(is_active=True).prefetch_related(
        "subcategories"
    )
    serializer_class = ScopeCategorySerializer
    permission_classes = [IsAuthenticated]


class ScopeSubCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Scope Subcategories
    """
    queryset = ScopeSubCategory.objects.filter(is_active=True)
    serializer_class = ScopeSubCategorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        return queryset


class MonthlyScopeWorkViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Monthly Scope of Work
    """
    queryset = MonthlyScopeWork.objects.all()
    serializer_class = MonthlyScopeWorkSerializer
    permission_classes = [IsAuthenticated, CanViewScopes]

    def get_queryset(self):
        queryset = MonthlyScopeWork.objects.select_related(
            'project', 'category', 'subcategory', 'created_by', 'updated_by'
        ).prefetch_related('assignments')

        user = self.request.user
        group_names = getattr(user, "_dpr_group_names", None)
        if group_names is None:
            group_names = set(user.groups.values_list("name", flat=True))
            user._dpr_group_names = group_names

        # Team Leaders can see all scopes
        if "Team Leader" in group_names:
            # Filter by project if specified
            project_id = self.request.query_params.get('project')
            if project_id:
                queryset = queryset.filter(project_id=project_id)

            # Filter by month if specified
            month = self.request.query_params.get('month')
            if month:
                queryset = queryset.filter(month=month)

        # Site Engineers can only see scopes assigned to them
        elif group_names & {
            "Site Engineer",
            "Billing Site Engineer",
            "QAQC Site Engineer",
        }:
            queryset = queryset.filter(assignments__site_engineer=user)

        return queryset.distinct()

    def _assign_scope_to_site_engineers(self, scope):
        """
        Automatically assign scope to Site Engineers only (not QAQC or Billing engineers)
        """
        from accounts.models import UserProfile

        # Get all site engineers assigned to the project
        project_engineers = scope.project.site_engineers.all()

        # Filter to only "Site Engineer" type (not QAQC or Billing)
        site_engineers = []
        for engineer in project_engineers:
            try:
                profile = engineer.profile
                if profile.site_engineer_type == 'site_engineer':
                    site_engineers.append(engineer)
            except UserProfile.DoesNotExist:
                # Skip users without profile
                continue

        # Create assignments for Site Engineers only
        assigned_count = 0
        for engineer in site_engineers:
            assignment, created = ScopeAssignment.objects.get_or_create(
                scope=scope,
                site_engineer=engineer,
                defaults={'assigned_by': scope.created_by}
            )
            if created:
                assigned_count += 1

    def perform_create(self, serializer):
        from django.db import transaction

        with transaction.atomic():
            scope = serializer.save(created_by=self.request.user)
            # Automatic assignment to Site Engineers only
            self._assign_scope_to_site_engineers(scope)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='project-scopes')
    def project_scopes(self, request):
        """
        Get scopes for a specific project
        """
        project_id = request.query_params.get('project_id')
        month = request.query_params.get('month')

        if not project_id:
            return Response(
                {'error': 'project_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = MonthlyScopeWork.objects.filter(project_id=project_id).select_related(
            "project", "category", "subcategory", "created_by", "updated_by"
        ).prefetch_related("assignments")

        if month:
            queryset = queryset.filter(month=month)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-scopes')
    def my_scopes(self, request):
        """
        Get scopes assigned to the current user
        """
        user = request.user

        # Check if user has access to view their scopes
        allowed_groups = ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer', 'Team Leader']
        if not user.groups.filter(name__in=allowed_groups).exists():
            return Response(
                {'error': 'You do not have permission to view assigned scopes'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get scopes assigned to this user
        queryset = MonthlyScopeWork.objects.filter(
            assignments__site_engineer=user
        ).select_related(
            'project', 'category', 'subcategory', 'created_by', 'updated_by'
        ).prefetch_related('assignments').distinct()

        # Filter by status if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by project if provided
        project_id = request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='progress')
    def progress(self, request, pk=None):
        """
        Get detailed progress information for a specific scope
        """
        scope_id = pk
        progress_data = ScopeProgressService.get_scope_progress_summary(scope_id)

        if progress_data is None:
            return Response(
                {'error': 'Scope not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Format response
        response_data = {
            'scope': {
                'id': progress_data['scope'].id,
                'project_name': progress_data['scope'].project.name,
                'category_name': progress_data['scope'].get_category_display_name(),
                'subcategory_name': progress_data['scope'].get_subcategory_display_name(),
                'description': progress_data['scope'].description,
                'unit': progress_data['scope'].unit,
            },
            'progress': {
                'planned_quantity': progress_data['planned_quantity'],
                'executed_quantity': progress_data['executed_quantity'],
                'remaining_quantity': progress_data['remaining_quantity'],
                'progress_percentage': progress_data['progress_percentage'],
                'status': progress_data['status'],
            },
            'tracking': {
                'total_dpr_entries': progress_data['total_dpr_entries'],
                'latest_dpr_date': progress_data['latest_dpr_date'],
                'daily_progress': progress_data['daily_progress'],
            }
        }

        return Response(response_data)

    @action(detail=True, methods=['post'], url_path='forward')
    def forward_scope(self, request, pk=None):
        """
        Forward/assign scope to site engineers
        """
        scope = self.get_object()

        # Check if user is Team Leader
        if not request.user.groups.filter(name='Team Leader').exists():
            return Response(
                {'error': 'Only Team Leaders can forward scopes'},
                status=status.HTTP_403_FORBIDDEN
            )

        site_engineer_ids = request.data.get('site_engineers', [])
        if not site_engineer_ids:
            return Response(
                {'error': 'site_engineers list is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get site engineers for this project
        project_site_engineers = scope.project.site_engineers.all()
        billing_engineer = scope.project.billing_site_engineer
        qaqc_engineer = scope.project.qaqc_site_engineer

        # Include all types of site engineers
        all_engineers = list(project_site_engineers)
        if billing_engineer:
            all_engineers.append(billing_engineer)
        if qaqc_engineer:
            all_engineers.append(qaqc_engineer)

        valid_engineer_ids = [eng.id for eng in all_engineers]

        # Validate that all provided IDs are valid for this project
        invalid_ids = [sid for sid in site_engineer_ids if sid not in valid_engineer_ids]
        if invalid_ids:
            return Response(
                {'error': f'Invalid site engineer IDs: {invalid_ids}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create assignments
        assignments_created = []
        for engineer_id in site_engineer_ids:
            assignment, created = ScopeAssignment.objects.get_or_create(
                scope=scope,
                site_engineer_id=engineer_id,
                defaults={'assigned_by': request.user}
            )
            if created:
                assignments_created.append(assignment)

        serializer = ScopeAssignmentSerializer(assignments_created, many=True)
        return Response({
            'message': f'Scope forwarded to {len(assignments_created)} site engineer(s)',
            'assignments': serializer.data
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsTeamLeader])
def forward_multiple_scopes(request):
    """
    Forward multiple scopes to site engineers
    """
    scope_ids = request.data.get('scope_ids', [])
    site_engineer_ids = request.data.get('site_engineers', [])

    if not scope_ids:
        return Response(
            {'error': 'scope_ids list is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not site_engineer_ids:
        return Response(
            {'error': 'site_engineers list is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get scopes
    scopes = MonthlyScopeWork.objects.filter(id__in=scope_ids)
    if len(scopes) != len(scope_ids):
        found_ids = set(scopes.values_list('id', flat=True))
        missing_ids = set(scope_ids) - found_ids
        return Response(
            {'error': f'Scopes not found: {list(missing_ids)}'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate all scopes belong to same project
    projects = set(scopes.values_list('project_id', flat=True))
    if len(projects) > 1:
        return Response(
            {'error': 'All scopes must belong to the same project'},
            status=status.HTTP_400_BAD_REQUEST
        )

    project_id = projects.pop()
    from projects.models import Project
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return Response(
            {'error': 'Project not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get site engineers for this project
    project_site_engineers = project.site_engineers.all()
    billing_engineer = project.billing_site_engineer
    qaqc_engineer = project.qaqc_site_engineer

    all_engineers = list(project_site_engineers)
    if billing_engineer:
        all_engineers.append(billing_engineer)
    if qaqc_engineer:
        all_engineers.append(qaqc_engineer)

    valid_engineer_ids = [eng.id for eng in all_engineers]

    # Validate engineers
    invalid_ids = [sid for sid in site_engineer_ids if sid not in valid_engineer_ids]
    if invalid_ids:
        return Response(
            {'error': f'Invalid site engineer IDs: {invalid_ids}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Create assignments for each scope-engineer combination
    assignments_created = []
    for scope in scopes:
        for engineer_id in site_engineer_ids:
            assignment, created = ScopeAssignment.objects.get_or_create(
                scope=scope,
                site_engineer_id=engineer_id,
                defaults={'assigned_by': request.user}
            )
            if created:
                assignments_created.append(assignment)

    serializer = ScopeAssignmentSerializer(assignments_created, many=True)
    return Response({
        'message': f'Created {len(assignments_created)} scope assignments',
        'assignments': serializer.data
    }, status=status.HTTP_201_CREATED)