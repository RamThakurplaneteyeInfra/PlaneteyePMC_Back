"""
Bottleneck register API — one item per Issue / Concern / Risk / Action.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAuthenticatedProjectRBAC
from accounts.rbac import RBACDomain, filter_queryset_by_project_access
from accounts.rbac_checks import enforce_project_access
from core.cache_keys import build_rbac_list_cache_key
from core.cache_ops import TTL_DASHBOARD
from core.cache_swr import get_or_rebuild
from core.cache_tags import invalidate_tags
from projects.models import Project

from .filters import BottleneckFilter
from .metrics import compute_summary
from .models import Bottleneck
from .serializers import BottleneckSerializer

_CACHE_SUMMARY = "bottlenecks_summary"


class BottleneckViewSet(viewsets.ModelViewSet):
    """
    CRUD for project bottleneck items.

    GET  /api/bottlenecks/?project_id=1&type=RISK&status=OPEN
    GET  /api/bottlenecks/summary/?project_id=1
    """

    serializer_class = BottleneckSerializer
    permission_classes = [IsAuthenticatedProjectRBAC]
    rbac_domain = RBACDomain.GENERAL
    filterset_class = BottleneckFilter

    def get_queryset(self):
        qs = (
            Bottleneck.objects.select_related(
                "project",
                "assigned_to",
                "created_by",
                "updated_by",
            )
            .all()
            .order_by("-created_at")
        )
        return filter_queryset_by_project_access(qs, self.request.user, "project")

    def _invalidate_caches(self):
        invalidate_tags("bottlenecks", "overview")

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )
        self._invalidate_caches()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
        self._invalidate_caches()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        self._invalidate_caches()

    @swagger_auto_schema(
        operation_summary="Bottleneck dashboard summary",
        manual_parameters=[
            openapi.Parameter(
                "project_id",
                openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                required=True,
                description="Project ID to summarize",
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        project_id = request.query_params.get("project_id")
        if not project_id:
            return Response(
                {"detail": "Query parameter project_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "project_id must be a valid integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            return Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        enforce_project_access(request.user, project)

        cache_key = build_rbac_list_cache_key(
            _CACHE_SUMMARY,
            request,
            extra_parts=[f"project:{project_id}"],
            use_query_string=False,
        )

        def _build():
            qs = self.get_queryset().filter(project_id=project_id)
            return compute_summary(qs)

        payload = get_or_rebuild(
            cache_key,
            _build,
            soft_ttl=TTL_DASHBOARD,
            hard_ttl=TTL_DASHBOARD * 2,
            prefix=_CACHE_SUMMARY,
        )
        return Response(payload)
