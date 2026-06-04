"""
Bottleneck register API — one item per Issue / Concern / Risk / Action.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .filters import BottleneckFilter
from .metrics import compute_summary
from .models import Bottleneck
from .serializers import BottleneckSerializer


class BottleneckViewSet(viewsets.ModelViewSet):
    """
    CRUD for project bottleneck items.

    GET  /api/bottlenecks/?project_id=1&type=RISK&status=OPEN
    GET  /api/bottlenecks/summary/?project_id=1
    """

    serializer_class = BottleneckSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = BottleneckFilter

    def get_queryset(self):
        return (
            Bottleneck.objects.select_related(
                "project",
                "assigned_to",
                "created_by",
                "updated_by",
            )
            .all()
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

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

        qs = self.get_queryset().filter(project_id=project_id)
        return Response(compute_summary(qs))
