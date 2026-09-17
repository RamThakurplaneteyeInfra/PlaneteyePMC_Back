"""Protected internal endpoints for external schedulers (e.g. GitHub Actions)."""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from dpr.services.executive_digest import send_dpr_executive_digest

logger = logging.getLogger("pmc.dpr.digest")
_LOG = "[DPR Digest]"


class DprExecutiveDigestTriggerView(APIView):
    """
    POST /api/internal/dpr/executive-digest/

    Authenticated only via shared secret header ``X-CRON-SECRET``.
    No JWT. No GET.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["post", "options", "head"]

    def post(self, request, *args, **kwargs):
        logger.info("%s Trigger received source=external_scheduler", _LOG)

        configured = getattr(settings, "DPR_DIGEST_CRON_SECRET", "") or ""
        if not configured:
            logger.warning("%s Scheduler not configured (missing secret)", _LOG)
            return Response(
                {
                    "success": False,
                    "message": "Digest scheduler is not configured.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        provided = request.headers.get("X-CRON-SECRET", "") or ""
        try:
            authorized = bool(configured) and secrets.compare_digest(provided, configured)
        except (TypeError, ValueError):
            authorized = False
        if not authorized:
            logger.warning("%s Authorization failed — invalid secret", _LOG)
            return Response(
                {
                    "success": False,
                    "message": "Unauthorized.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        logger.info("%s Authorization passed", _LOG)

        result = send_dpr_executive_digest(source="external_scheduler")
        status_value = result.get("status")
        date_str = result.get("date") or result.get("report_date")

        if status_value == "already_processed":
            return Response(
                {
                    "success": True,
                    "message": "DPR executive digest already processed for today.",
                    "data": {"status": "already_processed", "date": date_str},
                },
                status=status.HTTP_200_OK,
            )

        if status_value == "running":
            return Response(
                {
                    "success": False,
                    "message": "DPR executive digest is already being processed.",
                    "data": {"status": "running", "date": date_str},
                },
                status=status.HTTP_409_CONFLICT,
            )

        if status_value in ("queued", "sent"):
            message = (
                "DPR executive digest queued successfully."
                if status_value == "queued"
                else "DPR executive digest sent successfully."
            )
            return Response(
                {
                    "success": True,
                    "message": message,
                    "data": {
                        "status": status_value,
                        "date": date_str,
                        "recipient_count": result.get("recipient_count", 0),
                    },
                },
                status=status.HTTP_200_OK,
            )

        if status_value in ("disabled", "email_disabled"):
            return Response(
                {
                    "success": False,
                    "message": "Digest scheduler is not configured.",
                    "data": {"status": status_value, "date": date_str},
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if status_value == "skipped_no_recipients":
            return Response(
                {
                    "success": False,
                    "message": "DPR executive digest could not be processed.",
                    "data": {"status": status_value, "date": date_str},
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": False,
                "message": "DPR executive digest could not be processed.",
                "data": {"status": "failed", "date": date_str},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
