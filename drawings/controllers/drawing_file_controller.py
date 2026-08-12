"""Delete individual drawing file attachments."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from ..models.drawing_file import DrawingFile
from ..services.file_upload import soft_delete_drawing_file
from .drawing_controller import _flatten_errors


class DrawingFileViewSet(viewsets.GenericViewSet):
    """Soft-delete a drawing file and remove its S3 object."""

    queryset = DrawingFile.objects.select_related(
        "drawing_register", "drawing_register__project"
    ).filter(is_active=True)
    lookup_value_regex = r"\d+"

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    @swagger_auto_schema(
        operation_summary="Delete a drawing file attachment",
        tags=["Drawings"],
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
    )
    def destroy(self, request, *args, **kwargs):
        drawing_file = self.get_object()

        try:
            soft_delete_drawing_file(drawing_file=drawing_file, actor=request.user)
        except DjangoValidationError as exc:
            return self._error(
                "Failed to delete drawing file",
                errors=_flatten_errors(exc.message_dict),
            )

        return self._success(
            "Drawing file deleted successfully",
            {"id": drawing_file.id},
        )
