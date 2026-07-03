"""Alerts API — in-app notifications for the authenticated user."""

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .alerts_serializers import AlertReadStatusSerializer, AlertSerializer
from .models import Notification


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/alerts/ — list alerts for the current user.
    PATCH /api/alerts/{id}/ — mark read or unread.
    """

    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return (
            Notification.objects.filter(user=self.request.user)
            .select_related("project", "sender")
            .order_by("-created_at")
        )

    @swagger_auto_schema(
        operation_summary="List alerts for the current user",
        responses={200: AlertSerializer(many=True)},
        tags=["Alerts"],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data})

    @swagger_auto_schema(
        operation_summary="Retrieve a single alert",
        responses={200: AlertSerializer()},
        tags=["Alerts"],
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data})

    @swagger_auto_schema(
        operation_summary="Mark alert as read or unread",
        request_body=AlertReadStatusSerializer,
        responses={200: AlertSerializer()},
        tags=["Alerts"],
    )
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = AlertReadStatusSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "data": AlertSerializer(instance).data},
            status=status.HTTP_200_OK,
        )

    update = partial_update
